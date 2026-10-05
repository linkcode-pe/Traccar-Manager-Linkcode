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
