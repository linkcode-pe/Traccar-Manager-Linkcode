# Contrato y proveedor de API read-only v1 para el dashboard

**Estado:** contrato de datos y fachada interna aislada, con fuentes exclusivamente fixture/mock en pruebas. No hay servidor HTTP, endpoint, proveedor de producción, conexión a bases de datos ni conexión a Traccar. La web PHP existente no se modifica.

## 1. Propósito y límites

Definir el DTO estable que podría consumir el dashboard actual y separar:

```text
CONTRACT (DTOs, validación, errores)
    ↓
PROVIDER (RBAC, allowlist de provider, auditoría fail-closed)
    ↓
DATA SOURCE (interfaz inyectada; ninguno de producción en esta fase)
```

El contrato no contiene SQL, comandos, nombres de archivo ni selectores de servicio. No identifica en el DTO si una fuente futura es systemd, Traccar, MySQL o filesystem. `provider_id` existe únicamente como identidad interna de implementación para una allowlist confiable; nunca viene en el request ni se devuelve al frontend.

Archivos de esta fase:

- `api/read_only_dashboard_v1.py`: DTOs, validación, errores estables, Protocols de proveedor/RBAC/auditoría, fachada auditada y serialización determinista.
- `tests/test_api_readonly_v1.py`: fixtures, mock provider y mock audit sink; no usa sistemas externos.
- `docs/api-readonly-v1.md`: este contrato.

`api/dashboard_status_contract.py`, `worker/dispatcher/`, `worker/operations/traccar_status.py` y `worker/audit/` se mantienen sin cambios. El adaptador de status y el dispatcher no se ejecutan en las pruebas nuevas de provider. El flujo mock del status existente continúa cubierto por `tests/test_web_dashboard_contract.py`.

## 2. Recursos y DTOs

Hay **9 tipos DTO** contando request, valor, cinco modelos de recurso, servicio Traccar y envelope de dashboard. `ValueDTO` lleva `availability`, `value` y timestamp opcional. `DashboardSnapshotDTO` incluye `schema_version=1`, `request_id` y las cinco secciones fijas. Valores no disponibles no se representan como cero o texto vacío.

| DTO | Campos principales | Lo que no afirma |
|---|---|---|
| `ValueDTO` | estado `AVAILABLE`, `NOT_AVAILABLE` o `PENDING_PROVIDER`; escalar validado; timestamp opcional | no admite objetos arbitrarios ni secretos |
| `GeneralStatusDTO` | servicio Traccar: state, substate, load state, unit-file state, result; uptime, versión, overall state | uptime, versión y salud general siguen pendientes salvo proveedor explícito |
| `ServerMetricsDTO` | CPU %, memoria total/usada, disco total/libre y timestamp | métricas no obtenidas se marcan `PENDING_PROVIDER` |
| `DeviceSummaryDTO` | total, activos, inactivos y timestamp | no contiene nombre, uniqueid ni filas de dispositivos |
| `PositionSummaryDTO` | cantidad actual, cantidad antigua, estado disponible y timestamp | no contiene coordenadas, direcciones, uniqueid ni registros de posición |
| `RetentionStatusDTO` | configuración conocida, cutoff UTC, última ejecución y timestamp | no supone que exista un estado/cutoff accesible |
| `DashboardSnapshotDTO` | envelope versionado con general, server, devices, positions, retention | todos los submodelos deben estar presentes y validados |
| `DashboardRequestDTO` | únicamente `request_id` | no acepta recursos, SQL, tablas, servicios, rutas ni archivos elegidos por cliente |

Las cifras del fixture de pruebas son datos ficticios y solo validan tipos. Ningún DTO de fixture representa el estado actual del servidor.

### Estado de datos

- `AVAILABLE`: valor provisto y validado, con timestamp de sección/campo cuando se observó.
- `NOT_AVAILABLE`: un proveedor autorizado determinó que el dato no se ofrece; `value=null`.
- `PENDING_PROVIDER`: todavía no hay fuente/proveedor aprobado; `value=null`.

`pending_snapshot(request_id)` construye todas las secciones con `PENDING_PROVIDER`. La fachada, en cambio, responde `API_PROVIDER_UNAVAILABLE` si no hay provider configurado; no devuelve ese snapshot como si fuera una lectura válida.

## 3. Disponibilidad real conocida

El único adaptador operativo ya preparado es `worker/operations/traccar_status.py`: su contrato admite `LoadState`, `ActiveState`, `SubState`, `UnitFileState`, `Result`, unidad fija `traccar.service` y hora de observación. No se ejecutó. La prueba anterior de dashboard reemplaza el handler por un mock y pasa su resultado por dispatcher/contrato.

El modelo nuevo puede representar esos campos sin incluir el nombre de la fuente. No hay proveedor de producción para alimentar la fachada. El campo `overall_state` no se calcula a partir de `ActiveState`; uptime, versión y estado HTTP/aplicativo/DB tampoco se inventan.

El mapa web identifica contadores/posiciones, métricas de servidor y estados de retención que la antigua página obtenía mediante PDO, estado local o filesystem. En esta fase **ninguna** de esas fuentes se conecta: dispositivos, agregados de posiciones, CPU/memoria/disco y datos de retención quedan `PENDING_PROVIDER` hasta que exista un proveedor read-only aprobado. No se exponen filas de posición en el DTO.

## 4. Provider y Data Source

`DashboardDataSource` es un Protocol de lectura: `provider_id` confiable y `read_dashboard(DashboardRequestDTO) -> DashboardSnapshotDTO`. El provider solo acepta `provider_id` que esté en su allowlist inyectada por configuración confiable. No se instala una implementación concreta ni se permite seleccionar el provider desde el request.

`ReadOnlyDashboardProvider` aplica una lectura fija del snapshot completo. Comprueba request/actor, RBAC, existencia y allowlist del provider, registra las fases de auditoría y valida el snapshot devuelto. `FixtureSource` existe solo dentro de los tests. **Providers de producción implementados: 0.**

El caché idempotente de esta preparación es local a una instancia y conserva solo resultados completos; revalida RBAC en una repetición con el mismo `request_id` y actor. No reemplaza una clave/idempotency store durable en una futura API distribuida.

## 5. Request y seguridad

El request v1 acepta exactamente `{"request_id": "…"}`. `request_id` tiene longitud y alfabeto acotados. Cualquier clave adicional —incluidos `sql`, `command`, `shell`, `service`, `unit`, `path`, `file`, `table` o `provider`— se rechaza como `API_INVALID_REQUEST`.

No existen métodos de ejecución, conexión SQL, subprocess, shell, filesystem o selección de unidad. El provider solo recibe un request tipado y fijo. Cada Data Source futuro debe ser read-only, nombrado, probado y allowlisted; un Protocol por sí solo no concede autorización a instalar una fuente.

El actor se obtiene de contexto autenticado futuro; la política `ReadOnlyAuthorizer` comprueba RBAC para `dashboard.snapshot.read.v1`. Una lectura normal no necesita aprobación humana. La policy denegada no llega al Data Source. La autorización no ejecuta nada por sí sola.

## 6. Auditoría fail-closed

La interfaz `ReadAuditSink` recibe eventos compactos con `event_id`, `operation`, `request_id`, actor opaco, phase, result, `error_code`, timestamp UTC y `resource_type=dashboard_snapshot`. Los eventos no incluyen DTO, valores, coordenadas, consultas, DSN, credenciales, tokens ni contenido de excepciones.

Secuencia en un resultado completo:

```text
PREVIEW → AUTHORIZATION (RBAC) → AUDIT_PREPARE → EXECUTION → RESULT → AUDIT_FINALIZATION
```

`AUDIT_PREPARE` y `EXECUTION` deben confirmarse antes de invocar el Data Source. Si falla un append previo, el Data Source no se llama. Si falla `RESULT` o finalización después de una lectura, no se entrega el snapshot al caller. Los errores de auditoría se reducen a `API_AUDIT_UNAVAILABLE`.

La fachada exige un sink, y las pruebas demuestran el bloqueo ante fallos. El sink de las pruebas es un mock en memoria. No se agregó un adaptador de estas lecturas genéricas al `AuditLedger` real: su flujo actual está unido al dispatcher/allowlist de `traccar.status`. La integración con recibos durables requiere una fase que defina la operación/target y su puente sin eludir el dispatcher ni ampliar la allowlist implícitamente. Las consultas ordinarias siguen siendo RBAC, no autorización humana.

## 7. Errores estables

| Código | Uso |
|---|---|
| `API_INVALID_REQUEST` | request incompleto, malformado o con selector/campo extra |
| `API_UNAUTHORIZED` | falta contexto autenticado válido |
| `API_FORBIDDEN` | RBAC niega la lectura |
| `API_PROVIDER_UNAVAILABLE` | no hay provider o la fuente informa indisponibilidad |
| `API_DATA_UNAVAILABLE` | DTO incompleto, inválido o de otra request |
| `API_SOURCE_NOT_ALLOWED` | `provider_id` no está en la allowlist confiable |
| `API_TIMEOUT` | provider señala timeout |
| `API_AUDIT_UNAVAILABLE` | sink requerido no acepta la fase |
| `API_INTERNAL_ERROR` | fallo interno sanitizado |

`DashboardAPIError` expone solo uno de estos códigos. Mensajes de driver, SQL, excepciones y contenido de origen no se propagan.

## 8. Permisos y datos sensibles

La Web futura solo presenta DTOs. El provider/API no puede entregar coordenadas o direcciones a través de este contrato: `PositionSummaryDTO` contiene agregados mínimos. Para cualquier vista detallada de posiciones hará falta un scope/contrato y autorización separados. Conteos de dispositivos/posiciones pueden revelar actividad; RBAC debe limitar quién ve incluso los agregados.

No se cargan credenciales ni se consultan archivos de configuración. No se concede permiso a Worker/Web/API para SQL arbitrario, archivos arbitrarios o systemd general. El proveedor de `traccar.status` conserva su unidad fija y pasa por la allowlist de Worker; cualquier helper privilegiado es futuro y separado.

## 9. Pruebas aisladas

`tests/test_api_readonly_v1.py` prueba DTO válido/incompleto, campos extra, provider disponible/ausente/no permitido/erróneo/timeout, autorización RBAC, auditoría disponible/indisponible, privacidad de eventos, rechazo de SQL/shell/servicio/archivo, determinismo, idempotencia y snapshot completo con fixtures. No usa DB, Traccar, systemd, filesystem productivo, scripts o servidor HTTP.

Las pruebas del mock dispatcher/adaptador existentes permanecen separadas; al ejecutarlas se parchea `worker.operations.traccar_status.handle`, y no se consulta systemd.

## 10. Qué existe y qué falta

**Implementado en esta fase:** 9 tipos DTO validados, request allowlist, provider facade/Protocol, Protocol de Data Source, RBAC Protocol, audit sink Protocol con fail-closed, errores estables, serialización determinista, caché idempotente intra-instancia y mock provider/sink en tests.

**No implementado:** API HTTP, endpoints, autenticación real, provider de producción, lectura de MySQL/Traccar/filesystem, recolección CPU/memoria, scheduler/worker productivo, durable idempotency cache, adaptador de auditoría de este provider al ledger durable, ni modificación de la Web. El siguiente trabajo deberá elegir y autorizar por separado una fuente read-only por recurso, concretar permisos/RBAC y definir el puente durable al ledger, antes de publicar API o conectar la web existente.
