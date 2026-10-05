# Contrato de ejecución de tareas v1

**Estado:** contrato v1 y scaffolding fuente para `worker/dispatcher/`, `worker/audit/` y `traccar.status`. El dispatcher tiene una allowlist de una operación y un puerto de auditoría sin backend. No existen todavía API, Scheduler ejecutable, cola persistente, cuenta de servicio ni integración productiva; ningún job se despacha en esta fase.

**Independencia:** Traccar debe seguir funcionando aunque Traccar Manager esté detenido. El ciclo de vida básico de Traccar permanece bajo el sistema operativo/systemd y no depende del Scheduler, Worker ni API de Manager.

## 1. Alcance y documentos de referencia

Este contrato complementa `security-and-permissions-model.md`; no reemplaza la matriz de permisos, no habilita privilegios y no cambia archivos existentes. Sigue `architecture-overview.md` y `development-roadmap.md`: detección y reporte primero, sin borrado automático, con aprobación para acciones destructivas.

La estructura remota contiene `web/`, `runner/`, `scripts/`, `docs/`, `migrations/`, `tests/`, `release/`, `deployment/` e `installer/`; al iniciar esta fase no había `api/`, `worker/` ni `scheduler/`. Se agregan `worker/dispatcher/`, `worker/audit/`, marcadores de paquete y README; `worker/operations/traccar_status.py` queda como handler allowlist. `web/` contiene referencias PHP, no un flujo Manager API→Worker implementado. El nuevo código es fuente no ejecutada y no activa componentes.

Aclaración: `scripts/README.md` dice que no hay código ejecutable y que no se copien scripts del servidor, mientras existen allí tres scripts preservados como referencias. El modo no ejecutable no impide invocarlos mediante un intérprete. No se modificó ese README; las referencias siguen prohibidas para ejecución y esta operación no las importa.

## 2. Identidades y principios

- Web/API PHP, Scheduler, Worker normal y Migration Runner nunca ejecutan como root.
- Las operaciones se identifican mediante un nombre estable y un handler allowlist. No hay comandos, rutas, nombres de unidad, SQL ni parámetros de shell libres provenientes del usuario.
- Worker ordinario no tiene root, DDL, SQL arbitrario, acceso general a systemd ni filesystem completo.
- Cada principal, credencial y permiso se limita a una función; Manager DB y Traccar DB permanecen separados.
- Si no puede comprobarse identidad, autorización, integridad, estado previo o alcance, se detiene sin ejecutar.
- Los scripts de retención en `scripts/` son referencias; no se utilizan como handlers.

## 3. Sobre de Job

El formato lógico v1 de un job incluye como mínimo:

| Campo | Regla |
|---|---|
| `schema_version` | Entero conocido; versión desconocida se rechaza. |
| `job_id` | Identificador único e inmutable. |
| `operation` | Código exacto allowlist, por ejemplo `traccar.status`. |
| `payload` | Objeto validado contra el schema de esa operación; nunca texto de shell/SQL. |
| `requested_by` | Identidad autenticada de quien solicitó el job. |
| `created_at_utc` | Hora de creación UTC. |
| `scheduled_at_utc` | Hora UTC de ejecución o nulo para ejecución inmediata. |
| `idempotency_key` | Evita duplicar solicitudes equivalentes cuando se reintenta crear el job. |
| `preview_id` | Referencia a una vista previa vigente cuando la operación la requiere. |
| `authorization_id` | Referencia de aprobación de un solo uso; nulo en lecturas que no la requieren. |
| `attempt` | Número de intento controlado por Worker. |
| `handler_version` | Versión del handler que procesará el job. |

La cola oficial prevista para jobs PHP→Worker es Manager DB. Esta fase no crea ni altera su esquema; no ejecuta SQL ni migrations. Traccar DB no es la cola de Manager.

## 4. Contrato de autorización humana

Para cualquier operación clasificada como destructiva o privilegiada, una aprobación debe quedar ligada a **una sola operación** y a su alcance canónico exacto. Como mínimo incluye: identidad autenticada del aprobador, operación, recurso objetivo, hash del payload normalizado, `preview_id` y hash de preview, motivo, fecha de expiración, nonce/identificador de un solo uso y estado de consumo.

- No se puede reutilizar una aprobación para otra operación, servicio, ruta, rango de datos, parámetros, preview o job.
- Una aprobación vencida, consumida, incompleta o cuyo hash no coincide bloquea la ejecución.
- Cambiar un parámetro material invalida preview y aprobación; se requiere preview nueva y autorización nueva.
- `traccar.status` es una lectura: requiere autenticación/autorización RBAC para consultar estado, pero no aprobación humana por cada lectura.
- La existencia de una aprobación no concede permisos al proceso Web/API; el Worker y cada handler vuelven a validar el vínculo.

## 5. Estados y transiciones de Job

Estados permitidos: `QUEUED`, `CLAIMED`, `RUNNING`, `AWAITING_APPROVAL`, `SUCCEEDED`, `FAILED`, `RETRY_WAIT`, `RECOVERY`, `NEEDS_NEW_PREVIEW`, `CANCELLED` y `EXPIRED`.

Transiciones normales: `QUEUED → CLAIMED → RUNNING → SUCCEEDED|FAILED`. Una operación que requiere aprobación no pasa a ejecutable hasta verificarla. `CLAIMED/RUNNING` usan lease/heartbeat para detectar workers caídos, pero el vencimiento del lease no demuestra que el efecto no ocurrió.

Un resultado incierto pasa a `RECOVERY`; no se reintenta una acción potencialmente aplicada. Una alerta `CRITICAL` bloquea nuevas ejecuciones. El desbloqueo, si se implementa, requiere permiso y motivo y solo permite generar una nueva preview; la ejecución posterior usa un job nuevo.

## 6. Scheduler

- Scheduler crea ocurrencias y jobs elegibles; no ejecuta handlers, scripts, SQL ni comandos del sistema.
- La unicidad persistente del slot es `(task_id, scheduled_at_utc)`; las horas se guardan en UTC.
- Las tareas seguras pueden tener como máximo un catch-up dentro de la ventana aprobada de 15 minutos. Las destructivas no hacen catch-up automático.
- El Scheduler no puede crear una aprobación ni convertir una programación en permiso humano.
- Errores recuperables tienen un máximo de tres intentos según el handler. Fallo incierto va a `RECOVERY`; una alerta crítica no se limpia automáticamente.

## 7. Worker

- Corre bajo identidad dedicada no-root; reclama jobs mediante la cola de Manager DB, valida estado/lease, autorización aplicable, schema y allowlist antes de llamar a una operación.
- Ejecuta únicamente handlers registrados por código. Rechaza nombres de operación y campos desconocidos; nunca forma un comando usando payload.
- No invoca shell, SQL arbitrario, `systemctl` general ni acceso general al filesystem. No ejecuta migrations.
- Para status puede llamar solo al adaptador read-only descrito abajo, bajo identidad no-root. Un fallo de permisos se informa; no se corrige elevando privilegios.
- Registra resultado y estado final. No reintenta por cuenta propia operaciones inciertas.

## 8. Helpers

Cada helper futuro tiene una función, recurso allowlist, argumentos tipados, límites de tiempo y tamaño, resultado estructurado y códigos de error sanitizados. Los helpers no reciben órdenes de shell, SQL o rutas arbitrarias. Un helper root solo podrá existir en una fase separada, con autorización explícita, interfaz estrecha y aislamiento; este helper de estado no es root ni modifica unidades.

## 9. Auditoría

Cada solicitud/job debe permitir correlacionar: `request_id`, `job_id`, actor, operación, payload canónico/hash, preview/aprobación si aplica, slot, handler/version, intentos, timestamps, helper llamado, estado y resultado. Registrar por separado solicitud, aprobación, inicio, resultado confirmado, rechazo y recuperación. No registrar secretos, stderr bruto ni argumentos sensibles.

La ejecución debe detenerse si el mecanismo requerido de auditoría no está disponible. Se recomienda ledger append-only/WORM externo antes de operaciones críticas; su existencia no se afirma en esta fase.

## 10. Errores y recuperación

Códigos sanitizados previstos: `INVALID_JOB`, `UNKNOWN_OPERATION`, `UNAUTHORIZED`, `APPROVAL_REQUIRED`, `APPROVAL_MISMATCH`, `APPROVAL_EXPIRED`, `POLICY_DENIED`, `RUN_AS_ROOT_FORBIDDEN`, `DEPENDENCY_UNAVAILABLE`, `PERMISSION_DENIED`, `TIMEOUT`, `OUTPUT_INVALID`, `AUDIT_UNAVAILABLE` e `INTERNAL_ERROR`.

Los mensajes externos no incluyen excepciones crudas, SQL, rutas sensibles, stderr ni secretos. Un error solo es reintentable si el handler lo marca explícitamente como recuperable y la operación es segura para repetir. El máximo general son tres intentos; los resultados inciertos de operaciones con efectos pasan a `RECOVERY` sin reintento.

## 11. Primera operación: `traccar.status`

**Clasificación:** solo lectura. **Aprobación por ejecución:** no; requiere identidad autenticada y permiso RBAC de lectura. **DB:** ninguna. **Efectos:** ninguno. **Unidad fija:** `traccar.service`.

### Solicitud

`operation = "traccar.status"`; `payload = {}`. No se aceptan `unit`, comandos, argumentos, rutas, SQL ni otros parámetros. Web/API crea un job; Scheduler lo hace elegible; Worker valida y llama al adaptador no-root; el adaptador consulta systemd; Worker registra y devuelve el resultado.

### Helper preparado

`worker/operations/traccar_status.py` consulta exclusivamente `/usr/bin/systemctl show` para la unidad constante `traccar.service` y las propiedades `LoadState`, `ActiveState`, `SubState`, `UnitFileState` y `Result`. Usa argv fijo, `shell=False`, entorno mínimo y timeout de 5 segundos. Descarta stderr; valida que la salida contenga una sola vez cada propiedad allowlist; no devuelve PID, `ExecStart`, argumentos, logs ni configuración. Rechaza ejecución con UID 0 y payload no vacío. No acepta ni deriva la unidad de una entrada del usuario.

El resultado lógico contiene `schema_version`, `operation`, `result`, `observed_at_utc`, `source="systemd"`, `unit` y solo el mapa de propiedades allowlist. `ActiveState=active` significa que systemd reporta la unidad activa; no demuestra disponibilidad HTTP, salud de aplicación ni conexión a la base de datos. Un estado `failed` se informa, nunca provoca restart.

Errores del helper se limitan a códigos como `RUN_AS_ROOT_FORBIDDEN`, `SYSTEMD_UNAVAILABLE`, `SYSTEMD_PERMISSION_DENIED`, `SYSTEMD_TIMEOUT`, `SYSTEMD_QUERY_FAILED` u `OUTPUT_INVALID`; no exponen texto bruto. Timeout de esta consulta idempotente puede reintentarse de forma acotada; permiso denegado no se resuelve con elevación.

### Límite de implementación

Existe el handler `traccar.status`, el dispatcher allowlist y el contrato de auditoría, pero no hay API, Scheduler ejecutable, cola persistente, Worker loop, identidad dedicada, verifier ni backend de auditoría. No se invocó el helper ni se consultó el estado de producción; el flujo sigue sin ser funcional de extremo a extremo. Para activarlo se requiere una fase autorizada para identidad/permisos, cola/repository, Scheduler, autenticación, sink durable y pruebas bajo identidad no-root.

## 12. Contradicciones y cambios futuros

- `project-structure.md` no enumera `worker/`; esta fase añade `worker/dispatcher/` y `worker/audit/`, y completa el área existente `worker/operations/` con módulos de paquete y documentación. No implementa API, Scheduler ni Worker loop. Actualizar la descripción general del proyecto requiere una fase documental posterior.
- `scripts/README.md` contradice el estado actual de los scripts de referencia; no se corrige en esta fase. No incluirlos ni llamarlos desde el Worker.
- No cambiar archivos existentes para hacer coincidirlos automáticamente. Resolver divergencias antes de una futura integración.

## 13. Estado de esta fase

Se creó scaffolding Python no ejecutable para Job, allowlist dispatcher, interfaces de autorización/auditoría y el único adapter `traccar.status`; se documentó la identidad y los límites en `worker/README.md`. No se crean cuentas, tablas, API, Scheduler ejecutable, worker loop, sink de auditoría, unidades, timers ni permisos. El código no se ejecutó ni se integró con la cola. Las decisiones de despliegue y operación productiva requieren fases y autorizaciones separadas.
