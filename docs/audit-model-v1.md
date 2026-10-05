# Modelo de auditoría v1 — Traccar Manager

**Estado:** diseño exclusivamente documental. No crea un ledger, tabla, servicio, timer, usuario, permiso, credencial ni integración. No ejecuta Worker, Helper ni `traccar.status`.

## 1. Propósito y principios

La auditoría debe permitir reconstruir y demostrar quién solicitó qué operación, sobre qué objetivo, qué preview se generó, qué autorización se concedió, qué identidad ejecutó, cuándo ocurrió, cuál fue el resultado, si hubo rollback y qué errores se produjeron.

- Registro append-only: un evento persistido no se edita ni se elimina en la operación normal. Una corrección es otro evento que referencia al original.
- Denegar por defecto. Un evento de autorización o de auditoría no ejecuta la operación por sí solo.
- Web/API solicita y valida; Scheduler crea jobs elegibles; Worker despacha únicamente el registry permitido; Helpers realizan una función específica; el autorizador humano aprueba lo que la política clasifica como destructivo/privilegiado; Audit registra, pero no autoriza ni ejecuta.
- Ni Worker ni Helper reciben secretos como contenido de auditoría. El código actual de `AuditSink` es solo una interfaz y no es un ledger durable.
- Un fallo o ausencia de evidencia se representa explícitamente; nunca se presume éxito por silencio, timeout o caída de conexión.

Este modelo amplía `security-and-permissions-model.md` y `task-execution-contract-v1.md`. No reemplaza sus límites de mínimo privilegio ni declara que exista almacenamiento de auditoría en producción.

## 2. Fases separadas y puertas de ejecución

Las fases son acciones y eventos independientes; no se permite agrupar preview, autorización y ejecución en una llamada indivisible:

`REQUEST → VALIDATION → PREVIEW → AUTHORIZATION → EXECUTION → RESULT → AUDIT_FINALIZATION`

| Fase | Evidencia append-only | Límite |
|---|---|---|
| REQUEST | `REQUEST_RECEIVED` | Asignar `request_id` y `job_id`; identificar requester autenticado. No ejecutar. |
| VALIDATION | `VALIDATION_PASSED` o `VALIDATION_FAILED` | Validar operación, target, parámetros, identidad, estado del job y versión. No ejecutar. |
| PREVIEW | `PREVIEW_STARTED` y `PREVIEW_COMPLETED` o `PREVIEW_FAILED` | Producir un plan determinista y una referencia/hash inmutable. Sin efectos sobre el sistema observado. |
| AUTHORIZATION | `AUTHORIZATION_REQUESTED` y `AUTHORIZATION_GRANTED` o `AUTHORIZATION_DENIED` | Decisión independiente, ligada exactamente al preview, target, operación y parámetros. No ejecutar. |
| EXECUTION | `EXECUTION_STARTED`, luego `EXECUTION_COMPLETED` o `EXECUTION_FAILED`; o `EXECUTION_DENIED` | Volver a comprobar todos los gates. Registrar de forma durable `EXECUTION_STARTED` antes del primer efecto. |
| RESULT | Resultado confirmado o estado incierto más sus errores/rollback | Resultado tipado y sanitizado; no incluir salida bruta ni secretos. |
| AUDIT_FINALIZATION | `AUDIT_FINALIZED` | Cerrar la secuencia con recibo durable y verificar continuidad/hash. La falta de recibo no es éxito. |

No existen transiciones directas `RECEIVED → EXECUTING`, `PREVIEWING → EXECUTING` ni `AWAITING_AUTHORIZATION → EXECUTING`. Si falta o falla cualquier gate, el Worker no llama al Helper: registra `EXECUTION_DENIED`/`JOB_REJECTED` cuando el ledger lo permita y marca `NO_EXECUTION`.

### Puerta obligatoria

Antes de ejecutar deben verificarse, en este orden lógico: request válido; operación allowlisted; target permitido; parámetros normalizados válidos; preview válido y vigente; autorización válida y no consumida cuando corresponda; identidad Worker y Helper autorizada; ledger disponible y capaz de aceptar un append durable. Un rechazo nunca se reintenta automáticamente para convertirlo en ejecución.

La verificación previa del ledger debe producir un recibo durable. Una comprobación de salud sin append confirmado no basta para autorizar una operación crítica.

## 3. Preview determinista

El preview describe exactamente qué se haría, pero no lo hace. No modifica el sistema, no ejecuta una acción destructiva, no reinicia servicios, no ejecuta SQL destructivo, no cambia permisos ni activa componentes.

Un artefacto inmutable de preview incluye: `preview_id`, operación y versión, target canónico, parámetros normalizados y su hash, alcance/resultados previstos, precondiciones, plan de rollback o `NOT_SUPPORTED`, versión del generador, instante/identificador de snapshot si depende de datos variables, expiración y `preview_hash`.

- Canonicalizar antes de calcular hashes: orden estable de claves/colecciones, representación única de fechas y números, UTF-8, sin valores no finitos. Los datos dinámicos que afecten el plan quedan identificados en el preview.
- El artefacto puede incluir un resumen seguro y una referencia a los detalles; no contiene credenciales ni payloads sensibles sin redacción.
- `preview_hash` cubre la representación canónica completa del plan y sus precondiciones. La ejecución guarda el mismo `preview_id` y hash.
- Si cambian operación, target, parámetros relevantes, alcance, precondiciones materiales o versión del handler, rechazar con `E203_PREVIEW_MISMATCH` y pedir un preview nuevo.
- Para lecturas simples también hay una fase preview independiente: es un plan declarativo; no realiza la lectura real.

## 4. Autorización separada y de un solo uso

La autorización es un registro/decisión aparte del preview. El registro contiene como mínimo:

| Campo | Significado |
|---|---|
| `authorization_id` | Identificador único de la decisión/autorización. |
| `requester` | Identidad autenticada que originó el job. |
| `approver` | Humano autenticado para aprobación humana; o identidad explícita del motor RBAC para permisos de lectura sin aprobación humana. |
| `operation`, `target` | Operación y objetivo canónicos permitidos. |
| `preview_id`, `preview_hash` | Preview exacto aprobado. |
| `timestamp`, `expiration` | Emisión y vencimiento UTC. |
| `authorization_scope` | Alcance tipado, sin valores secretos, ligado al hash de parámetros/preview. |
| `parameters_hash` | Huella de los parámetros normalizados aprobados. |
| `one_time_nonce`, `consumed_at`, `consumed_by_job_id` | Prevención y evidencia de reutilización. |
| `decision`, `approval_mode` | `GRANTED`/`DENIED`; por ejemplo `HUMAN` o `RBAC_READ`. |

Reglas:

- Una autorización solo vale para el mismo job/operación/target/alcance/preview/hash, mientras no expire y no haya sido consumida. El consumo debe ser atómico antes de ejecución.
- Preview o alcance distintos invalidan la autorización; no se renueva ni adapta silenciosamente.
- Una autorización ausente, inválida, expirada o ya consumida significa `EXECUTION = DENIED`; no llamar al Helper.
- Las operaciones `destructive = true` exigen aprobación humana explícita después del preview. La programación del Scheduler no sustituye ni crea esa aprobación.
- Para lecturas allowlist como `traccar.status`, la fase de autorización es una decisión RBAC separada, no una aprobación humana por cada consulta. No se omiten los eventos de autorización.
- No se presupone que requester y approver deban ser dos personas distintas; si una política futura exige doble control, deben ser identidades humanas autenticadas distintas. Worker, Scheduler y Zapia nunca cuentan como aprobador humano.

## 5. Esquema de evento v1

Cada append tiene un sobre común. Los campos condicionales se escriben como `null` o se omiten según el serializador canónico definido antes de implementar; el significado debe mantenerse idéntico en todos los productores.

```json
{
  "event_id": "UUID",
  "event_type": "REQUEST_RECEIVED",
  "event_version": 1,
  "timestamp": "RFC3339 UTC",
  "ledger_sequence": 1,
  "job_id": "job-id",
  "request_id": "request-id",
  "operation": "traccar.status",
  "operation_version": "handler-version",
  "target": {"type": "systemd-unit", "id": "traccar.service"},
  "requester": {"subject_id": "pseudonymous-id", "actor_type": "human"},
  "approver": null,
  "worker_identity": null,
  "helper_identity": null,
  "authorization_id": null,
  "preview_id": null,
  "preview_hash": null,
  "authorization_scope": null,
  "authorization_scope_hash": null,
  "parameters_hash": "digest",
  "previous_event_id": null,
  "previous_event_hash": null,
  "status": "ACCEPTED",
  "error_code": null,
  "result_code": null,
  "rollback_status": "NOT_APPLICABLE",
  "duration_ms": null,
  "event_hash": "digest"
}
```

Reglas de campos:

- `event_id`: único e inmutable. `event_type` pertenece al catálogo cerrado de la sección 6; `event_version` identifica la versión del sobre, inicialmente `1`.
- `timestamp`: UTC RFC3339 generado por el componente de auditoría confiable. Para ordenar se usa `ledger_sequence`, no solo relojes de hosts.
- `job_id` es obligatorio para eventos de job/ejecución; `request_id` correlaciona desde la recepción hasta el resultado. `operation` es obligatoria; `target` es canónico y obligatoria cuando aplique.
- `requester` siempre identifica al iniciador con un ID estable/pseudónimo, nunca un token. `approver` se completa en decisiones; identifica humano o motor RBAC según `approval_mode`.
- `worker_identity` se completa en eventos de ejecución; `helper_identity` solo cuando un helper fue llamado. Registrar principal lógico y versión, no secretos ni argumentos del proceso.
- `authorization_id`, `preview_id`, `preview_hash` y `authorization_scope` deben repetirse en las fases posteriores cuando aplican, para probar el enlace exacto.
- `parameters_hash` es obligatorio. No guardar payload sensible ni SQL. Se calcula sobre representación canónica redactada; campos sensibles usan HMAC-SHA-256 con clave de auditoría protegida y `hash_key_id` versionado, nunca la clave ni el valor en el evento. Para parámetros no sensibles se puede usar SHA-256 canónico. Si la política no permite una huella segura, rechazar en vez de registrar el valor bruto.
- `status` usa valores definidos por evento (`PASSED`, `FAILED`, `GRANTED`, `DENIED`, `STARTED`, `COMPLETED`, `AUDIT_FAILURE`, etc.); no es un mensaje libre. `error_code` es solo un código estable. `result_code` es un código de resultado sanitizado, no stdout/stderr.
- `rollback_status` usa `NOT_APPLICABLE`, `NOT_STARTED`, `REQUIRED`, `IN_PROGRESS`, `COMPLETED`, `FAILED` o `NOT_SUPPORTED`. `duration_ms` es entero no negativo y solo se llena cuando existe duración medible.
- Extensiones de integridad: `ledger_sequence`, `previous_event_hash`, `event_hash`, `preview_hash`, `authorization_scope_hash`, `operation_version` y `hash_key_id` cuando se usa HMAC. No deben cambiar la semántica del sobre v1.

Los eventos no almacenan contraseñas, tokens, claves privadas, trust stores, secretos, payloads sensibles, SQL con credenciales, stderr bruto ni datos de ubicación innecesarios. Los mensajes humanos se mantienen fuera del código de error estable.

## 6. Catálogo de eventos

Cada nombre tiene una sola semántica. Eventos marcados **requerido** son mínimos en v1.

| Event type | Semántica |
|---|---|
| `REQUEST_RECEIVED` **requerido** | Request autenticado recibido y correlacionado. |
| `VALIDATION_PASSED` **requerido** | Todos los checks de request/operación/target/params de esa etapa pasaron. |
| `VALIDATION_FAILED` **requerido** | Algún check falló; lleva `error_code`, sin ejecución. |
| `PREVIEW_STARTED` **requerido** | Comienza la generación pura del preview. |
| `PREVIEW_COMPLETED` **requerido** | Artefacto determinista guardado/referenciado por `preview_id` y hash. |
| `PREVIEW_FAILED` **requerido** | No fue posible producir un preview válido. |
| `AUTHORIZATION_REQUESTED` **requerido** | Se solicita una decisión independiente para alcance/preview exactos. |
| `AUTHORIZATION_GRANTED` **requerido** | Decisión concedida, modo y alcance exactos registrados. |
| `AUTHORIZATION_DENIED` **requerido** | Decisión rechazada, expirada, inválida o no demostrable. |
| `EXECUTION_STARTED` **requerido** | Gate completo y append durable antes de invocar operación/helper. |
| `EXECUTION_COMPLETED` **requerido** | Resultado de ejecución confirmado; no significa éxito si `result_code` indica otra cosa. |
| `EXECUTION_FAILED` **requerido** | Ejecución confirmó fallo; incluye código estable y estado de resultado. |
| `EXECUTION_DENIED` **requerido** | Puerta de ejecución rechazó el job; el handler/helper no fue llamado. |
| `ROLLBACK_STARTED` **requerido** | Inicia únicamente el rollback previsto y permitido por contrato. |
| `ROLLBACK_COMPLETED` **requerido** | Rollback confirmado; no borra ni sustituye el fallo original. |
| `ROLLBACK_FAILED` **requerido** | Rollback falló o no puede confirmarse. |
| `AUDIT_WRITE_FAILED` **requerido** | Un append esperado no pudo confirmarse durablemente; requiere canal independiente si el ledger principal falla. |
| `JOB_REJECTED` **requerido** | Job terminalmente rechazado sin ejecutar la operación. |
| `AUDIT_FINALIZED` | Secuencia del job cerrada con recibo durable y validación de integridad. |
| `AUDIT_INTEGRITY_FAILURE` | Hash, secuencia, cadena o checkpoint no coincide; incidente crítico, no autoriza reparación destructiva del ledger. |
| `AUDIT_RECONCILIATION` | Evento nuevo que documenta reconciliación manual posterior; nunca edita eventos previos. |

Un rechazo por validación produce `VALIDATION_FAILED` y `JOB_REJECTED`; una denegación en el gate produce `EXECUTION_DENIED` y `JOB_REJECTED`. No emitir `EXECUTION_STARTED` si la operación no se invocó.

## 7. Máquina de estados e idempotencia

Estados v1: `RECEIVED`, `VALIDATED`, `PREVIEWING`, `PREVIEWED`, `AWAITING_AUTHORIZATION`, `AUTHORIZED`, `EXECUTING`, `SUCCEEDED`, `FAILED`, `ROLLBACK_REQUIRED`, `ROLLING_BACK`, `ROLLED_BACK`, `ROLLBACK_FAILED`, `REJECTED`. Estado de integridad de auditoría es una dimensión separada: `OK`, `AUDIT_FAILURE` o `AUDIT_INTEGRITY_FAILURE`.

| Desde | Hacia permitido | Condición |
|---|---|---|
| `RECEIVED` | `VALIDATED`, `REJECTED` | Request schema/identidad comprobados. |
| `VALIDATED` | `PREVIEWING`, `REJECTED` | Policy y alcance aptos para preview. |
| `PREVIEWING` | `PREVIEWED`, `FAILED`, `REJECTED` | Preview completo y hash persistido, o fallo explícito. |
| `PREVIEWED` | `AWAITING_AUTHORIZATION`, `AUTHORIZED`, `REJECTED` | Aprobación humana pendiente; o autorización RBAC no humana concedida; o denegación. |
| `AWAITING_AUTHORIZATION` | `AUTHORIZED`, `REJECTED` | Decisión humana válida, o denegación/expiración. |
| `AUTHORIZED` | `EXECUTING`, `REJECTED` | Revalidar bindings, consumo de autorización y append durable `EXECUTION_STARTED`. |
| `EXECUTING` | `SUCCEEDED`, `FAILED`, `ROLLBACK_REQUIRED` | Resultado confirmado; si incierto, bloquear y tratarlo como fallo/recuperación, nunca como éxito. |
| `ROLLBACK_REQUIRED` | `ROLLING_BACK`, `FAILED` | Rollback existe, está permitido y se conoce el estado requerido. |
| `ROLLING_BACK` | `ROLLED_BACK`, `ROLLBACK_FAILED` | Resultado de rollback confirmado o fallido. |

`REJECTED`, `SUCCEEDED`, `FAILED`, `ROLLED_BACK` y `ROLLBACK_FAILED` son terminales para ejecución automática. Una conciliación posterior añade eventos y evidencia; no reinicia el job ni altera historial. `AUDIT_FAILURE` bloquea nuevas ejecuciones relacionadas; no se limpia automáticamente.

Idempotencia:

- `idempotency_key` único por request canónico. Un duplicado idéntico devuelve/referencia el job ya existente; no crea una segunda ejecución.
- La autorización es de un solo uso y su consumo debe ser atómico. Reutilizarla produce `E304_AUTHORIZATION_ALREADY_USED` y no invoca el helper.
- Reintentar la escritura de un evento usa el mismo `event_id`/contenido para deduplicación; no generar eventos distintos que aparenten dos ejecuciones.
- Expirar un lease o perder SSH no prueba que el efecto no ocurrió. Si el resultado es incierto, no reintentar una operación potencialmente destructiva; dejar evidencia de estado desconocido y requerir conciliación.

## 8. Destructividad, rollback y auditoría

La catalogación por operación debe incluir `destructive`, `approval_required`, `preview_required`, `rollback_supported`, versión y el contrato de efectos. Para `destructive = true`:

`VALIDATION → PREVIEW → HUMAN AUTHORIZATION → EXECUTION → RESULT/AUDIT`

- `preview_required = true`; nunca ejecutar directamente desde un job programado.
- La autorización humana cubre un único preview/target/alcance y se consume una sola vez.
- Antes de autorizar se conoce si el rollback es compatible, qué snapshot/respaldo se requiere y cuál es el plan. `NOT_SUPPORTED` debe mostrarse antes de autorizar; no prometer rollback inexistente.
- El rollback tiene eventos y autorización/alcance propios según su contrato. Nunca reemplaza, oculta ni borra `EXECUTION_FAILED` o el resultado original.
- Una tarea fallida no se repite automáticamente cuando su efecto parcial o total no puede descartarse.

## 9. Append-only e integridad verificable

Diseño de referencia, no implantado:

1. Ledger autoritativo independiente de la cola/status mutable de Manager DB; preferir almacenamiento externo append-only/WORM con retención controlada. Una tabla o archivo ordinario no basta para afirmar inmutabilidad.
2. Un único secuenciador lógico por partición asigna `ledger_sequence`, serializa append concurrentes y exige que `previous_event_id` y `previous_event_hash` coincidan con el último append confirmado. Conflicto/fork produce `E800_CONCURRENCY_CONFLICT` o `E702_AUDIT_INTEGRITY_FAILURE` y bloquea ejecución.
3. `event_hash = SHA-256(domain_separator || previous_event_hash || canonical_event_bytes)`, donde `canonical_event_bytes` incluye todos los campos del evento excepto `event_hash`. Genesis usa previos nulos. El algoritmo, canonicalizador, encoding y test vectors deben congelarse antes de implementar.
4. Un append devuelve recibo durable con secuencia, `event_id` y `event_hash`. Lectores/auditores tienen acceso de solo lectura; procesos Web/API/Worker no poseen permisos para editar/borrar entradas históricas.
5. Hash chains detectan cambios y huecos internos, pero no por sí solas la truncación del último tramo. Emitir checkpoints periódicos con raíz/hash y guardarlos en un segundo dominio append-only/WORM, con firma/verificación administrada aparte. Una discrepancia es `AUDIT_INTEGRITY_FAILURE`.
6. Restauración/verificación del ledger es un procedimiento separado, evidencia append-only y aprobación propia; no se reescribe la cadena para “arreglarla”.

El ledger, WORM, secuenciador, claves de checkpoint, backups y recibos no están verificados ni creados en esta fase.

## 10. Fallos de auditoría

### `AUDIT_FAIL_BEFORE_EXECUTION`

Si el append durable obligatorio (incluido `EXECUTION_STARTED`) no puede confirmarse: registrar `AUDIT_WRITE_FAILED` si existe el canal independiente, establecer `NO_EXECUTION`, devolver `E700_AUDIT_UNAVAILABLE` o `E701_AUDIT_WRITE_FAILED` y **no invocar** Worker/Helper para ejecutar. No hacer un bypass ni reintentar automáticamente una petición rechazada.

### `AUDIT_FAIL_DURING_OR_AFTER_EXECUTION`

No inventar rollback automático. Aplicar el contrato de la operación:

- Detener pasos adicionales si es seguro hacerlo y no repetir la acción.
- Si el resultado es confirmado y existe rollback aprobado, definido y seguro para el estado observado, ejecutar solo ese rollback conforme a sus gates y auditarlo por canal durable.
- Si reversibilidad/resultado no se puede verificar, no intentar rollback a ciegas; marcar `AUDIT_FAILURE`, resultado operativo `UNKNOWN` y bloquear reintentos/ejecuciones relacionadas para conciliación humana.
- Registrar el incidente mediante canal independiente. Si el ledger primario y el canal independiente fallan, no afirmar que el evento está auditado; generar alerta fuera de banda y mantener `OPERATION_STATE = UNKNOWN`.
- En tareas críticas, `AUDIT_INTEGRITY_FAILURE` detiene nuevas ejecuciones. La pérdida de auditoría nunca se convierte silenciosamente en éxito.

## 11. Códigos de error estables

Códigos inmutables, documentados, no localizados y no reutilizables. Cambiar el texto humano no cambia el código. `error_code` almacena solo uno de estos tokens; detalles internos sanitizados quedan aparte y nunca contienen secretos.

| Código | Significado único |
|---|---|
| `E100_OPERATION_NOT_ALLOWED` | Operación conocida pero prohibida por policy. |
| `E101_INVALID_OPERATION` | Nombre/schema de operación inválido o desconocido. |
| `E102_INVALID_TARGET` | Target fuera de allowlist o mal formado. |
| `E103_INVALID_PARAMETERS` | Parámetros no válidos para schema de operación. |
| `E104_UNAUTHORIZED_REQUESTER` | Requester no autenticado o sin permiso de solicitud. |
| `E200_PREVIEW_REQUIRED` | Falta preview requerido. |
| `E201_PREVIEW_INVALID` | Preview inexistente, mal formado o no verificable. |
| `E202_PREVIEW_EXPIRED` | Preview vencido. |
| `E203_PREVIEW_MISMATCH` | Operación/target/params/scope/versión difiere del preview. |
| `E300_AUTHORIZATION_REQUIRED` | Falta autorización aplicable. |
| `E301_AUTHORIZATION_INVALID` | Autorización inválida o no verificable. |
| `E302_AUTHORIZATION_EXPIRED` | Autorización vencida. |
| `E303_AUTHORIZATION_SCOPE_MISMATCH` | Alcance no coincide exactamente. |
| `E304_AUTHORIZATION_ALREADY_USED` | Autorización de un solo uso ya consumida/reutilizada. |
| `E400_WORKER_NOT_AUTHORIZED` | Identidad Worker no permitida para el job. |
| `E401_HELPER_NOT_AUTHORIZED` | Helper/operación no autorizado. |
| `E402_PRIVILEGE_INSUFFICIENT` | Permisos mínimos no disponibles; no elevar automáticamente. |
| `E403_IDENTITY_MISMATCH` | Identidad real no coincide con job/policy. |
| `E500_EXECUTION_FAILED` | Operación confirmó fallo. |
| `E501_EXECUTION_TIMEOUT` | Timeout; resultado puede ser incierto según contrato. |
| `E502_TARGET_UNAVAILABLE` | Target no disponible. |
| `E503_OPERATION_ALREADY_RUNNING` | Conflicto con operación ya activa para el mismo alcance. |
| `E600_ROLLBACK_REQUIRED` | Contrato/resultado requiere evaluar rollback. |
| `E601_ROLLBACK_FAILED` | Rollback falló o no se confirmó. |
| `E602_ROLLBACK_NOT_SUPPORTED` | No existe rollback permitido/definido. |
| `E700_AUDIT_UNAVAILABLE` | Ledger no disponible antes de ejecución. |
| `E701_AUDIT_WRITE_FAILED` | Append requerido no se confirmó durablemente. |
| `E702_AUDIT_INTEGRITY_FAILURE` | Cadena, checkpoint, secuencia o integridad falló. |
| `E800_CONCURRENCY_CONFLICT` | Colisión/fork/compare-and-append concurrente. |
| `E801_JOB_NOT_FOUND` | Job solicitado no existe. |
| `E802_JOB_STATE_INVALID` | Transición/estado no permitido. |
| `E803_AUTHORIZATION_SERVICE_UNAVAILABLE` | No se pudo obtener/verificar una decisión RBAC; deny-by-default. |
| `E900_INTERNAL_ERROR` | Error interno no clasificable; mensaje sanitizado y sin texto bruto. |

No añadir códigos con significado duplicado; las implementaciones deben probar la tabla contra un catálogo versionado.

## 12. Aplicación conceptual a `traccar.status`

- Operación: `traccar.status`; `destructive = false`; payload `{}`; target allowlist único `traccar.service`; campos de resultado permitidos: `LoadState`, `ActiveState`, `SubState`, `UnitFileState`, `Result`.
- REQUEST/VALIDATION comprueban requester autenticado, registry, target constante y payload exactamente vacío.
- PREVIEW crea un plan declarativo determinista con operación, unidad fija, propiedades, helper/versión y hash. No llama `systemctl`, no consulta estado real ni modifica nada.
- AUTHORIZATION genera decisión RBAC separada para el permiso de lectura; no exige aprobación humana por cada lectura. Se registra `authorization_id` con `approval_mode = RBAC_READ`.
- EXECUTION solo podría invocar al Worker/adapter autorizado después de append durable `EXECUTION_STARTED`. Resultado solo contiene valores allowlist y timestamp; error usa código estable. `rollback_status = NOT_APPLICABLE`.
- Debe emitirse resultado y finalización de auditoría; no consultar secretos, logs, base de datos ni propiedades fuera de allowlist.

Esta operación **no se ejecutó** en esta fase.

## 13. Coherencia y brechas de implementación

- El modelo es compatible con la separación y mínimo privilegio de `security-and-permissions-model.md`, y detalla el registro append-only recomendado allí.
- `task-execution-contract-v1.md` y el dispatcher/`AuditEvent` actuales son scaffolding, no ledger. El protocolo presente solo describe una fracción de campos y `append()` no entrega recibo durable; por tanto todavía no cumple este modelo.
- El dispatcher actual usa etiquetas provisionales (`VALIDATED`, `OPERATION_STARTED`, `OPERATION_SUCCEEDED/FAILED`) y no registra preview/auth completa. Deben mapearse a los event types canónicos y ampliar el sobre antes de una implementación runtime.
- El Job/dispatcher actual rechaza `preview_id`/`authorization_id` para `traccar.status`. Este diseño propone un preview estático del plan y una autorización RBAC con `authorization_id`, sin aprobación humana. Alinear código y contrato requiere una fase posterior autorizada; no se cambia código ahora.
- No hay backend append-only/WORM, RBAC verifier, secuenciador, checkpoints, canal de incidentes, API/Scheduler/Worker productivos ni persistencia probada. No afirmar durabilidad, idempotencia o integridad operativa hasta implementar y validar esas piezas.

## 14. Alcance de esta fase

El resultado de esta fase es este modelo documental. No implementa tablas, SQL, Worker, Helper, autorizador, storage, WORM, hashes en producción, permisos, servicios, timers ni conexiones a bases de datos. Los cambios productivos y cualquier autorización humana real requieren fases separadas.
