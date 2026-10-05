# Centro de mantenimiento — Fase 4 v1

## Alcance inicial

La primera operación nueva es **preview de retención de logs**. Es deliberadamente no destructiva: clasifica qué logs históricos serían candidatos y calcula cantidad/bytes, pero no elimina ni modifica archivos.

Política inicial:

- directorio de producción previsto: `/opt/traccar/logs`;
- retención predeterminada: **90 días**;
- solo nombres `tracker-server.log.YYYYMMDD`;
- `tracker-server.log` activo nunca puede ser candidato;
- symlinks no son candidatos;
- el directorio debe ser absoluto, existente, directorio real y no symlink;
- rango de retención permitido por el núcleo: 30–3650 días;
- cutoff estricto: solo `mtime < cutoff`;
- resultado determinista con nombre, ruta, bytes y mtime UTC;
- ninguna acción destructiva ocurre durante preview.

## Secuencia de entrega

1. Núcleo puro de preview + pruebas (este incremento).
2. Contrato Worker/RBAC/auditoría para `maintenance.logs.preview`.
3. Endpoint y tarjeta del dashboard.
4. Validación read-only contra producción.
5. Diseñar `maintenance.logs.execute` por separado, ligado criptográficamente al preview/confirmación y con rollback/evidencia apropiados.

No se reutiliza directamente el script destructivo `traccar_log_retencion_30d.sh` desde la web. Ese script queda como referencia histórica hasta que la ejecución controlada tenga contrato propio.

La retención de posiciones/MySQL permanece fuera de este incremento y no se toca.

## Incremento 2 — Worker + RBAC + auditoría

`maintenance.logs.preview` ya está definido como operación del protocolo UDS del Worker. Acepta únicamente `retention_days` entre 30 y 3650, exige el rol servidor `maintenance.logs.preview` y usa el directorio fijo `/opt/traccar/logs`; el cliente no puede suministrar rutas.

La operación recorre el flujo auditado de nueve eventos (request, validation, preview, autorización RBAC_READ, audit prepare, result y finalization) sobre el ledger compartido. Se añadió un recibo de finalización genérico verificable para operaciones read-only que no tienen el schema específico de systemd.

Este incremento **no está desplegado en producción y no expone todavía una ruta HTTP ni botón en el dashboard**. Tampoco existe operación de borrado. El siguiente incremento será el cliente Manager/UDS y la API/UI de preview, manteniendo la operación no destructiva.

## Incremento 3 — Manager API y dashboard de Preview

El Manager incorpora el puente `Manager -> UDS -> Worker` para `maintenance.logs.preview`, verifica el recibo contra el ledger compartido antes de devolver datos y expone `GET /api/maintenance/logs/preview` únicamente a sesiones con el rol correspondiente. El dashboard añade un Centro de mantenimiento con retención configurable (30–3650 días), cantidad de candidatos, bytes potencialmente recuperables y listado de archivos candidatos.

La interfaz usa exclusivamente nodos de texto para representar nombres/fechas devueltos por el Worker y conserva explícitamente `destructive_action_performed=false`. **No existe endpoint, botón ni operación de borrado en este incremento.** Este código permanece en la rama Phase 4 y aún no está desplegado en producción.

## Incremento 4 — Validación HTTP/UI aislada

La ruta HTTP y la UI fueron ejercitadas en un `ManagerHTTPServer` efímero ligado exclusivamente a `127.0.0.1`, con sesión y proveedor ficticios. Se validó HTTP 200 para una sesión con `maintenance.logs.preview`, rechazo 401 sin sesión, rechazo de parámetros fuera de política y de cualquier intento de introducir una ruta arbitraria, además de 405 para POST. La página real contiene el Centro de mantenimiento y no contiene control de eliminación.

Esta validación no accedió a MySQL, a la base de datos de Traccar ni ejecutó limpieza. No requiere ni implica despliegue del código Phase 4 en los servicios persistentes.

## Regla visual oficial — continuidad con `/panel`

La interfaz de Traccar Manager adopta como referencia visual oficial el `/panel` original del servidor: fondo azul-negro, tarjetas oscuras con bordes discretos, acento cian, estados semánticos, radios moderados, jerarquía compacta y diseño responsive. La referencia se traduce a componentes propios del Manager; no se copia la lógica PHP ni el acceso directo de `/panel` a MySQL. Esta regla aplica a login, dashboard, mantenimiento y módulos futuros para conservar una identidad única.

## Incremento 5 — Preview operativo enriquecido

El Preview de logs incorpora métricas de inventario no destructivas: cantidad y tamaño total de logs históricos allowlisted, cantidad y bytes candidatos y rango temporal de los candidatos. El dashboard presenta estas métricas en tarjetas siguiendo el sistema visual derivado de `/panel`. El contrato conserva `active_log_protected=true` y `destructive_action_performed=false`; no se incorpora endpoint, permiso ni botón de eliminación.

La futura limpieza real queda deliberadamente fuera de este incremento. Antes de implementarla deberá definirse un protocolo independiente de preparación/confirmación que vincule una autorización efímera a un `preview_id` inmutable y vuelva a validar los archivos inmediatamente antes de cualquier mutación.

## Incremento 6 — núcleo PREPARED sin ejecución

Se incorpora el contrato puro `log_retention_prepare`: recibe exclusivamente un `preview_id` válido y la retención, vuelve a escanear la ruta fija `/opt/traccar/logs`, recalcula el hash del plan y falla con `PREVIEW_STALE` si cualquier candidato cambió. Si coincide, crea una preparación efímera de 5 minutos ligada al hash, conteo/bytes y nonce de un solo uso. El resultado declara `destructive_action_performed=false`.

Este incremento **no expone todavía endpoint HTTP/UDS, no concede `maintenance.logs.prepare` a ninguna cuenta y no contiene executor de borrado**. La siguiente puerta es integrar esta preparación con auditoría durable y el protocolo Worker; solo después podrá mostrarse en UI.

## Incremento 6 — Gate de Execute sin mutación
Se añadió el contrato puro `maintenance.logs.execute` en estado de diseño/gate, todavía no expuesto por HTTP/UDS ni habilitado en producción. Exige preparación válida, frase explícita `CONFIRMAR LIMPIEZA`, nonce exacto, TTL vigente y revalidación completa del Preview inmediatamente antes de ejecutar. El resultado actual fija `execution_enabled=false`, `authorization_consumed=false` y `destructive_action_performed=false`; no existe llamada a unlink/remove/rm. El próximo gate deberá resolver persistencia/consumo atómico de la preparación y autorización antes de incorporar cualquier mutación real.

## Incremento 7 — Consumo durable de un solo uso
El gate Execute incorpora un `PreparationConsumptionStore` append-only con lock exclusivo `flock`, binding hash de todos los campos sensibles de la preparación y `fsync` antes de devolver éxito. Una preparación consumida vuelve a fallar con `PREPARATION_ALREADY_CONSUMED`; una colisión del mismo `preparation_id` con binding distinto falla cerrada. Validaciones fallidas no consumen la preparación. Este store todavía se prueba únicamente en fixtures temporales: no está conectado a HTTP/UDS ni a producción y el gate mantiene `execution_enabled=false` y `destructive_action_performed=false`.

## Incremento 8 — Dispatch y auditoría de Execute bloqueado
Se incorporó `maintenance_execute_dispatch` para probar la cadena de auditoría completa del futuro Execute: request, validation, preview/revalidation, authorization requested/granted, `AUDIT_PREPARE`, result y finalization. El gate consume durablemente la preparación una sola vez, pero el resultado contractual es `BLOCKED_BY_FEATURE_GATE`; `execution_enabled=false` y `destructive_action_performed=false`. No está registrado en runtime UDS/HTTP ni desplegado. No existe primitiva de borrado en este camino.

## Incremento 9 — Helper destructivo confinado a sandbox
Se añadió un helper que sí ejecuta `unlink`, pero únicamente contra un directorio sandbox explícito y nunca contra `/opt/traccar` ni `/opt/traccar/logs`. Revalida raíz, nombre allowlisted, tipo de archivo, tamaño y mtime inmediatamente antes del unlink; usa `dir_fd` y `follow_symlinks=false` para reducir escapes/TOCTOU. Las pruebas usan exclusivamente `TemporaryDirectory`, comprueban preservación del log activo, cambio posterior al Preview, sustitución por symlink, mismatch de raíz y conteos exactos. Este helper NO está conectado al Execute, Dispatcher, UDS, HTTP ni producción.

## Incremento 10 - Semantica de fallo parcial en sandbox
El helper sandbox ejecuta preflight completo antes de mutar, revalida identidad inmediatamente antes de cada unlink y rechaza candidatos duplicados. Una prueba con hook exclusivo de test fuerza una carrera entre la segunda revalidacion y el segundo unlink: tras una primera eliminacion valida, el helper responde `PARTIAL_DELETE`. No intenta rollback ficticio. El hook no esta conectado a runtime y el hard-deny de `/opt/traccar` permanece.

## Incremento 11 - Security review Execute
Revision integral registrada en `docs/m2-execute-security-review-2026-10-05.md`. Resultado: **NO-GO** para runtime destructivo. Se identificaron cuatro bloqueantes: Preparation sin prueba durable de emision, consumo anterior a AUDIT_PREPARE, parameters_hash incompleto y authorization sintetica. El helper permanece sandbox-only y Execute sigue feature-gated.

## Incremento 11 - PreparationStore durable ligado al actor
Se implementó un store append-only para demostrar que una preparación fue emitida por el sistema y pertenece al actor que intenta usarla. El binding cubre `subject_id` y todos los campos de `LogRetentionPreparation`, incluido nonce, hashes, TTL y conteos. El archivo usa lock, `fsync`, modo 0600 y `O_NOFOLLOW`; preparaciones no emitidas, actor distinto, contenido manipulado o store symlink fallan cerrado. Este store aún no está conectado al runtime/producción; resuelve el núcleo del bloqueante B1 antes de modificar el orden B2.

## Incremento 12 - Orden durable AUDIT_PREPARE antes de consumo
El dispatch Execute fue reordenado para separar revalidación de consumo. Primero valida/revalida sin gastar la preparación, registra y verifica durablemente `AUDIT_PREPARE`, y solo entonces ejecuta el consumo one-shot. Una prueba con fallo inyectado de `prepare_execution` demuestra que `AUDIT_UNAVAILABLE` deja el store de consumo inexistente; una ruta exitosa demuestra que el consumo ocurre después del prepare durable. Execute sigue bloqueado y sin helper destructivo conectado.

## Incremento 13 - Binding completo y señalización web segura
El Execute aislado vincula preparación completa + actor + confirmación + huella del nonce al `parameters_hash` y puede exigir emisión previa actor-bound. La UI de Manager muestra explícitamente el flujo `Analizar -> Preparar -> Ejecutar bloqueado`, para que la preparación visible no se interprete como borrado habilitado. La mejora web no incorpora endpoint Execute ni acción destructiva.

## Incremento 14 - Visibilidad de controles de Execute en Manager
La UI de producción puede exponer, únicamente después de una preparación auditada válida, los controles ya validados en código aislado: binding de sesión/actor, auditoría durable antes del consumo, autorización one-shot anti-replay y revalidación del plan. Esto es transparencia de estado, no habilitación: el tercer paso permanece `Ejecutar bloqueado` y no existe endpoint destructivo web.

## Incremento 15 - PreparationStore integrado al Worker
El flujo PREPARE del Worker ahora registra cada preparación exitosa en un `PreparationStore` durable propiedad del Worker, vinculada al `subject_id`, después de finalizar y verificar la auditoría. El store reside bajo `/var/lib/traccar-manager-worker/maintenance-preparations.jsonl`, no contiene primitivas destructivas y todavía no habilita Execute. La UI refleja que la preparación está ligada a sesión y registrada durablemente.

## Incremento 16 - Attestation durable de PREPARE hasta la Web
El Worker ahora incluye `preparation_stored=true` únicamente cuando el `PreparationStore` confirmó persistencia. El cliente UDS exige ese campo y falla cerrado si falta o es falso; Manager lo conserva y la UI solo muestra la confirmación durable si recibió esa attestation. Esto elimina una afirmación puramente visual: la Web refleja una propiedad confirmada extremo a extremo por Worker. Execute permanece bloqueado y no se consume ninguna preparación desde la UI.

## Incremento 16 - Verificación final no destructiva de readiness
PREPARE ahora, después de persistir y verificar el binding actor/preparación, ejecuta el mismo gate de Execute en modo `consume=false`, usando el nonce real internamente y revalidando el Preview. Solo si el gate confirma `execution_enabled=false` y `destructive_action_performed=false`, Worker emite `execution_readiness=READY_BLOCKED`. UDS y Manager validan esa attestation exacta antes de propagarla. La web muestra entonces `Listo para ejecutar · bloqueo de seguridad activo`. No se consume el nonce y no existe llamada al helper destructivo.

## Incremento 17 - Contrato de frontera destructiva aislada
Se formalizó la frontera destructiva como componente sandbox-only: `production_access=false`, raíz productiva `/opt/traccar/logs` hard-denied, allowlist estricta `tracker-server.log.YYYYMMDD` y log activo denegado. La UI publica este estado de arquitectura sin desplegar el helper destructivo ni habilitar Execute. El próximo gate deberá convertir este contrato en un servicio privilegiado separado con identidad/permisos mínimos antes de cualquier acceso productivo.

## Incremento 18 - Contrato del futuro servicio privilegiado
Se añadió un contrato puro, sin side effects, para la futura frontera privilegiada. Declara `DENY_PRODUCTION`, identidad separada obligatoria, sin red ni shell, una sola operación `DELETE_EXPIRED_HISTORICAL_LOGS`, nombres históricos allowlisted y log activo denegado. No se creó usuario privilegiado, socket, sudoers, capability ni permiso sobre `/opt/traccar/logs`; por diseño esta fase sólo valida el protocolo antes de crear la identidad del servicio.

## Incremento 19 - Servicio de frontera instalado en modo DENY_PRODUCTION
Se implementó el servidor Unix local de la frontera con identidad separada y unit systemd endurecida. Su única respuesta actual es health/contrato; declara `production_access=false` y `destructive_action_performed=false`. No importa el helper destructivo, no tiene red, shell, capabilities ni `ReadWritePaths` hacia `/opt/traccar/logs`. La UI refleja la existencia del servicio separado, pero Execute continúa bloqueado.

## Incremento 20 - Health real Worker -> Retention Boundary
Se añadió un cliente estricto del Worker para el socket Unix de Retention Boundary. El cliente acepta únicamente el contrato completo `healthy + DENY_PRODUCTION + production_access=false + destructive_action_performed=false`; cualquier respuesta parcial o alterada falla cerrada. El socket expone exclusivamente health y es local AF_UNIX; no existe operación destructiva servida. Se validó la consulta ejecutándola con la identidad real `traccar-manager-worker`.

## Incremento 21 - Health dinámico Boundary → Worker → Manager → Web
Manager consulta el estado de la frontera mediante el UDS existente del Worker. Worker consulta a su vez el socket Unix aislado de Retention Boundary y valida el contrato exacto `DENY_PRODUCTION`. La web obtiene el resultado mediante un endpoint autenticado; cualquier fallo muestra `Frontera no disponible · operación bloqueada`. No se habilita Execute ni acceso destructivo.

## Incremento 22 - Execute protocol probado contra gate final DENY_PRODUCTION
Retention Boundary acepta ahora una solicitud estructurada exclusivamente para `DELETE_EXPIRED_HISTORICAL_LOGS` con nombres allowlisted. Una solicitud válida se valida y alcanza el gate final, que responde `DENIED_BY_PRODUCTION_GATE`; una solicitud con log activo, traversal u operación fuera de allowlist se rechaza antes. En todos los casos `production_access=false` y `destructive_action_performed=false`. No existe mutación productiva.

## Incremento 23 - Plan real de Prepare alcanza Boundary sin mutación
Después de revalidar Preview y persistir la preparación, Worker extrae exactamente los nombres candidatos del Preview revalidado y los envía a Retention Boundary. Boundary valida la allowlist y responde `DENIED_BY_PRODUCTION_GATE`. El resultado vuelve por Worker/UDS/Manager y la UI muestra el número real de candidatos cuyo Execute fue rechazado. `production_access=false` y no existe borrado.

## Incremento 24 - Estado vacío fail-closed en UI
Cuando Preview devuelve cero candidatos, Manager descarta `lastPreview`, oculta Prepare y muestra explícitamente `Sin candidatos · Prepare y Execute deshabilitados · no hay nada que eliminar`. El flujo termina sin emitir preparación ni solicitud Execute. Esto evita que un preview vacío pueda convertirse accidentalmente en autorización ejecutable.

## Incremento 25 - Revalidación final privilegiada preparada
Se añadió una revalidación read-only destinada exclusivamente a Retention Boundary antes de cualquier futura mutación: nombre exacto `tracker-server.log.YYYYMMDD`, fecha del nombre realmente expirada según retención, apertura relativa al directorio con `O_NOFOLLOW`, archivo regular y rechazo de symlinks/traversal/log activo. Todavía no está conectada a una ruta destructiva y Boundary permanece `DENY_PRODUCTION`.

## Hotfix - Dashboard UDS timeout budget
El dashboard auditado puede completar correctamente después de más de 8 segundos bajo carga; se observaron finalizaciones Worker válidas inmediatamente después de que Manager ya había agotado su timeout. El presupuesto local UDS se eleva a 15 segundos (acotado), manteniendo fail-closed y sin retries. Esto evita falsos `PROVIDER_UNAVAILABLE` sin relajar validación, identidad, auditoría ni permisos.

## Incremento 26 - Revalidación final conectada al Execute de Boundary
La solicitud Execute ahora incluye `retention_days`. Retention Boundary revalida cada candidato contra `/opt/traccar/logs` justo antes del gate final: nombre, expiración, archivo regular y `O_NOFOLLOW`. Si alguno falla responde `DENIED_BY_REVALIDATION`; sólo si todos pasan responde `DENIED_BY_PRODUCTION_GATE` con `revalidated_count=N`. Sigue sin existir mutación. Se conserva además el timeout UDS de dashboard validado en 15 s.

## Incremento 27 - Ejecutor destructivo validado exclusivamente en sandbox
Se implementó el primer ejecutor que realiza una mutación real, pero contiene una barrera de ruta que sólo autoriza directorios bajo `/tmp/traccar-manager-retention-sandbox/` y exige autorización explícita de sandbox. Reutiliza la revalidación final y elimina mediante `unlink(..., dir_fd=...)`. Las pruebas demuestran borrado de histórico sandbox, rechazo de symlink, rechazo sin autorización y rechazo absoluto de `/opt/traccar/logs`. El servicio productivo no importa ni invoca este ejecutor; `DENY_PRODUCTION` permanece intacto.

## Incremento 28 - Auditoría durable del ejecutor sandbox
Cada ejecución destructiva de sandbox genera ahora evidencia JSONL durable antes de considerarse validada: `preparation_id`, candidatos solicitados, cantidad revalidada, archivos eliminados, evidencia `active_log_included=false`, `production_access=false`, timestamp, enlace al hash previo y hash del registro. La escritura usa `O_NOFOLLOW`, append y `fsync`. El audit path está restringido al sandbox. Producción continúa sin importar/invocar este ejecutor.

## Incremento 29 - Fallo parcial fail-stop y evidencia exacta
El ejecutor sandbox ahora registra resultado por archivo. Ante el primer `unlink` fallido se detiene: separa `deleted_names`, `failed_names` y `not_attempted_names`, devuelve `SANDBOX_PARTIAL_FAILURE` y persiste exactamente el mismo resultado en la auditoría durable. Nunca declara éxito total después de un fallo. Producción permanece `DENY_PRODUCTION`.

## Incremento 30 - Protección TOCTOU por identidad de archivo
El ejecutor sandbox abre cada candidato con `O_NOFOLLOW`, captura `st_dev/st_ino`, vuelve a consultar el nombre inmediatamente antes del unlink y exige que siga apuntando al mismo archivo regular. Si el nombre fue sustituido, devuelve `IDENTITY_CHANGED`, entra en fail-stop, no elimina el reemplazo y audita el incidente. Producción continúa `DENY_PRODUCTION`.

## Incremento 31 - Execute single-use y concurrencia
Cada `preparation_id` sandbox debe adquirir un claim durable mediante creación atómica `O_CREAT|O_EXCL` antes de revalidar o mutar. Bajo 12 consumidores concurrentes exactamente uno obtiene el claim y los demás reciben `PREPARATION_ALREADY_CONSUMED`. Los claims están restringidos al sandbox y `/opt/traccar/logs` es rechazado. Esto protege doble clic, retry y carreras concurrentes. Producción continúa `DENY_PRODUCTION`.

## Incremento 32 - Fingerprint inmutable del plan Execute
El ejecutor sandbox vincula la autorización al contenido exacto mediante SHA-256 canónico sobre operación, `preparation_id`, lista ordenada tal como fue preparada y `retention_days`. La verificación ocurre antes del claim y de cualquier mutación. Cambiar ID, candidato o retención produce `PLAN_FINGERPRINT_MISMATCH`; no se crea claim ni se toca el archivo. La comparación usa `hmac.compare_digest`. Producción sigue `DENY_PRODUCTION`.

## Incremento 33 - Autenticidad HMAC del plan
Se añadió el primitivo HMAC-SHA256 que autentica la huella canónica del plan exacto. Exige clave >=32 bytes y usa `hmac.compare_digest`; cualquier cambio de candidatos, retención o clave invalida el token. En esta fase el secreto no se crea ni se entrega a Manager/UI: el módulo queda preparado para que únicamente Retention Boundary cargue la clave desde credencial systemd en el siguiente gate. Producción sigue `DENY_PRODUCTION`.

## Incremento 34 - Secreto HMAC aislado como systemd credential
Se añadió un cargador fail-closed que sólo acepta `retention-plan-hmac.key` desde `$CREDENTIALS_DIRECTORY`. La unidad Boundary recibe la clave mediante `LoadCredential=`; no se expone por variables de entorno, Manager ni Worker. La fuente persistente queda root-only y systemd materializa una copia privada para el servicio. Producción continúa `DENY_PRODUCTION`.

## Incremento 35 - Emisión y verificación HMAC dentro de Boundary
Retention Boundary carga su credencial systemd y expone dos acciones locales todavía no destructivas: `ISSUE_AUTH` firma el plan exacto y `VERIFY` exige el token antes de revalidar. Alterar ID, candidatos o retención invalida el token (`DENIED_BY_PLAN_AUTH`). Incluso un token válido termina en `DENIED_BY_PRODUCTION_GATE`; no existe mutación productiva en este protocolo.

## Incremento 36 - Autorización por identidad Unix del peer
Boundary valida `SO_PEERCRED` en cada conexión sensible y sólo acepta `ISSUE_AUTH`/`VERIFY` cuando el UID real corresponde a `traccar-manager-worker`. El socket deja de ser world-writable: se publica `0660` con grupo `traccar-manager-worker`. La unidad Boundary recibe ese grupo como suplementario exclusivamente para poder asignarlo al socket. Manager/UI queda fuera del canal criptográfico. Producción continúa `DENY_PRODUCTION`.

## Incremento 37 - HMAC vinculado a preparación durable y TTL
`ISSUE_AUTH` ya no firma sólo ID+candidatos+retención: exige `preparation_binding_hash`, `issued_at_utc` y `expires_at_utc`, limita la vigencia a 300 segundos y rechaza preparaciones expiradas. El token incorpora binding+expiración, por lo que cambiar el registro durable o extender/reutilizar su TTL invalida `VERIFY`. SO_PEERCRED y socket 0660 permanecen activos; producción sigue `DENY_PRODUCTION`.

## Incremento 38 - Evidencia durable de PREPARE verificada por Boundary
Antes de `ISSUE_AUTH`, Boundary exige encontrar `preparation_id + binding_hash` exactos en una vista de atestaciones durable y sólo lectura. Un ID inexistente o binding alterado no puede obtener HMAC. El store autoritativo de Worker conserva actor+preparación; Boundary sólo recibe la evidencia mínima necesaria. TTL, SO_PEERCRED, socket 0660 y `DENY_PRODUCTION` permanecen activos.

## Incremento 39 - Publicación automática de atestaciones PREPARE
Tras persistir y verificar una preparación, Worker publica `preparation_id + binding_hash` en un spool append-only bajo `/run/traccar-manager`. Un helper root independiente copia sólo registros válidos y nuevos hacia la vista root-owned/Boundary-readable; Worker no puede escribir la vista consumida por Boundary ni sobrescribir registros previos. El flujo destructivo continúa bloqueado.


## Incremento 40 - Sync root E2E de atestaciones activo
Se instaló `traccar-manager-attestation-sync.path/service`: observa el spool Worker, valida registros mínimos y sólo añade pares nuevos a `/var/lib/traccar-manager-retention/preparations.jsonl`. Verificación productiva: Worker crea spool 0600; helper root sincroniza; Worker no puede escribir la vista; Boundary sí puede leerla. Traccar permanece sin reinicio y producción sigue `DENY_PRODUCTION`.

## Incremento 41 - PREPARE conectado al protocolo HMAC real de Boundary
El flujo normal de `maintenance.logs.prepare` usa ahora el binding devuelto por `PreparationStore`, publica la atestación y solicita a Boundary `ISSUE_AUTH`; después presenta ese token mediante `VERIFY`. El cliente tolera únicamente la breve carrera de sincronización root y exige como resultado final exacto `DENIED_BY_PRODUCTION_GATE`. La vista de atestaciones de Boundary queda fijada al path root-owned `/var/lib/traccar-manager-retention/preparations.jsonl`.

## Incremento 42 - Identidad PREVIEW estable durante el día
La prueba E2E productiva detectó que `cutoff_utc` variaba cada segundo, haciendo que un PREPARE inmediato pudiera fallar `PREVIEW_STALE`. Se corrige de forma fail-closed: el cutoff de retención se normaliza a 00:00:00 UTC del día límite. La lista, tamaños y mtimes de candidatos siguen formando parte del hash; cualquier cambio real en candidatos continúa invalidando PREPARE. Suite de mantenimiento: 28/28 OK. Producción permanece DENY_PRODUCTION.

## Incremento 43 - Contrato EXECUTE de consumo único
El gate no destructivo de EXECUTE exige ahora nonce válido dentro de la preparación durable. `PreparationConsumptionStore` liga el consumo a preparation_id, preview, retención, candidatos, vigencia y one_time_nonce, persiste con flock+fsync y rechaza replay como `PREPARATION_ALREADY_CONSUMED`. El consumo ocurre sólo después de AUDIT_PREPARE. No existe unlink en este incremento; producción permanece DENY_PRODUCTION.


## Incremento 44 - EXECUTE conectado al runtime UDS Worker
El runtime productivo reconoce `maintenance.logs.execute`, reconstruye una `LogRetentionPreparation` tipada y ejecuta el dispatcher auditado con PreparationStore + ConsumptionStore durables. La secuencia permanece `AUDIT_PREPARE → consume once → FEATURE_GATE_BLOCKED`; no existe unlink. Suite UDS ejecutada como usuario Worker: 16/16 OK.
