# Puente aislado Web → contrato API read-only v1

**Alcance:** referencia de cliente y harness para demostrar consumo del DTO v1 por las funciones del dashboard, sin endpoint, red ni fuentes sensibles. Los seis archivos PHP/CSS/JS existentes bajo `web/` no se modifican. El adaptador no reemplaza ni rediseña la página.

## 1. Artefactos

- `web/adapters/dashboard_client_v1.py`: cliente de contrato de referencia que construye el request único, decodifica JSON estricto y transforma DTO a un view-model semántico de las tarjetas existentes. No hace `fetch`, no toca DOM, no autentica, no conoce rutas HTTP, SQL, archivos ni servicios.
- `tests/test_web_api_bridge_v1.py`: harness que alimenta el adaptador con un snapshot JSON producido por la fachada API read-only y fuentes fixture.
- Este documento: matriz de funciones y límites.

Es una prueba aislada del **contrato entre datos y campos de la interfaz**, no una conexión ejecutable desde el PHP actual: no existe endpoint HTTP y no se agregó integración de red al `app.js`. Login, HTML, CSS, JavaScript y rutas existentes se mantienen intactos. La autenticación de producción queda fuera de esta fase.

## 2. Flujo probado

```text
request fijo de dashboard
 → ReadOnlyDashboardProvider (fixture)
 → PREVIEW / AUTHORIZATION RBAC / AUDIT_PREPARE / EXECUTION
 → FixtureMetrics + FixtureTraccar
 → RESULT / AUDIT_FINALIZATION
 → JSON DTO v1
 → dashboard_client_v1.py
 → modelo semántico de tarjetas existentes
```

El request es exactamente `{"request_id":"…"}`; el conjunto de recursos es fijo y no admite tabla, SQL, unidad, servicio, shell, ruta o archivo. Las fuentes son fixtures. Si falla el append de auditoría previo, la fuente no se llama ni se obtiene DTO. Los fallos de proveedor se exponen con código API estable, sin detalle de excepción.

## 3. Mapeo de la web existente

| Función actual | Mapeo al contrato | Resultado en esta fase |
|---|---|---|
| Login/logout y sesión | Fuera del snapshot | Se conservan como referencia, sin credenciales ni cambios de autenticación |
| Tarjeta MySQL | No hay DTO/proveedor de DB en esta fase | `PENDING_PROVIDER`; no conectar directo a MySQL |
| Tarjeta estado Traccar | `GeneralStatusDTO.traccar_service` (state, substate, load/unit-file state, result, timestamp) | Consumible desde fixture; fuente real/systemd y versión/uptime/health pendientes |
| CPU, memoria, disco | `ServerMetricsDTO` | El mapper puede consumir los campos; tests usan fixture. Fuente procfs/statvfs real no se ejecutó |
| Conteos de dispositivos | `DeviceSummaryDTO` | DTO soporta total/active/inactive; proveedor sigue pendiente, por eso no muestra ceros falsos |
| Conteos/estado de posiciones | `PositionSummaryDTO` | Agregados permitidos; proveedor pendiente; filas/identificadores/coords/direcciones permanecen `PENDING_PROVIDER` |
| Retención 90d | `RetentionStatusDTO` genérico no identifica política/tarea | Se mantiene `PENDING_PROVIDER`; no atribuir un estado genérico a retención de posiciones |
| Retención de logs 30d | `RetentionStatusDTO` no distingue este proceso | Se mantiene `PENDING_PROVIDER`; se necesita DTO/proveedor específico posterior |
| Actualizar | `build_dashboard_request(request_id)` | Solo construye el request tipado; todavía no hay llamada HTTP ni endpoint |
| Tabla de posiciones actuales | Sin DTO de filas detalladas | Se conserva como función visual de la web, pero datos no disponibles; no fabricar filas vacías como si no hubiera posiciones |

El view-model también mantiene la semántica separada de `AVAILABLE`, `NOT_AVAILABLE` y `PENDING_PROVIDER`; los valores no disponibles se devuelven como `null`, nunca como 0. El renderizador futuro deberá usar el escape HTML de la página existente.

## 4. Seguridad y fallos

El decoder exige el conjunto exacto de propiedades del DTO: campos ausentes, duplicados, extra, datos de posiciones no autorizados o JSON malformado se rechazan como `API_DATA_UNAVAILABLE`. El request adapter produce una sola clave. El mapper no agrega nombres de proveedor a la respuesta, credenciales, coordendas, direcciones, IDs de dispositivos ni filas de posición.

Los providers de sistema y estado se invocan solo detrás de la fachada autenticada/auditada en la composición de prueba. Una fuente no allowlisted se rechaza antes de llamarla. Una fuente pendiente no se sustituye por datos inventados. Auditoría indisponible bloquea la lectura y la devolución.

## 5. Validación de interfaz

Antes y después se calcularon SHA-256 de los seis archivos de `web/`; los hashes no cambiaron. Por ello se conserva el código fuente de la estructura, login, tarjetas, tablas, CSS y JavaScript. La validación fue por hashes y por el mapping unitario; no se inició un servidor ni se hizo una comprobación visual de navegador, ya que no hay endpoint y esta fase prohíbe publicar uno.

La prueba no invoca SQL, shell, systemd, scripts, Worker, Scheduler ni Helpers. No usa Apache, credenciales, archivos protegidos ni una fuente de producción.

## 6. Pendientes y fase futura

Para conectar el PHP real todavía hacen falta: proveedor aprobado para DB/dispositivos/posiciones, status de Traccar a través de la allowlist Worker, DTOs separados para retenciones 90d y 30d, bridge durable de auditoría, API HTTP autenticada/RBAC y un cliente PHP/JS que consuma ese endpoint. Cada acceso sensible requiere fase y autorización propias. No se debe exponer coordenadas/direcciones ni leer secretos en Web.
