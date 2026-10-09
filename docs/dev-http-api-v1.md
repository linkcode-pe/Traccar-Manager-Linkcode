# API HTTP read-only v1 — DEVELOPMENT_ONLY

## Estado y límites

Servidor local de prueba dentro de Manager. **DEVELOPMENT_ONLY**. `build_server()` bindea exclusivamente IPv4 loopback `127.0.0.1`; no acepta host configurable, no tiene integración Apache/VirtualHost, no instala servicios systemd ni ofrece listeners públicos. `main()` exige opt-in explícito `TRACCAR_MANAGER_DEV_API=1`. No iniciar como producción.

El API usa únicamente `FixtureDashboardDataSource`, que delega en `FixtureMetricsSource` y `FixtureStatusSource`; ambos devuelven valores sintéticos fijos y no leen OS, systemd, Traccar, DB ni filesystem. No se llaman `SystemMetricsProvider` ni `TraccarStatusProvider`. El sink por defecto conserva eventos compactos solo en la memoria del proceso.

## Endpoint único

```text
GET /api/v1/dashboard/status?request_id=<id>
```

Identidad fixture de desarrollo (no es credencial real): `X-Development-Identity: fixture-dashboard-reader`. Está mapeada en el servidor a `dashboard.read`. El cliente no puede suministrar roles. `fixture-no-dashboard-role` y una identidad desconocida se rechazan. Solo existe ese path y un único `request_id`; no se acepta body, selector de recurso/servicio, shell, ruta, archivo, tabla ni SQL.

POST/PUT/PATCH/DELETE/OPTIONS/HEAD/TRACE/CONNECT devuelven 405 y `Allow: GET`. Errores contienen solo el código estable, sin stack, excepción, ruta ni detalles. Las respuestas exitosas usan `snapshot_to_json()` y exclusivamente `DashboardSnapshotDTO`.

## Autorización y auditoría

```text
REQUEST HTTP → PREVIEW → AUTHORIZATION → AUDIT_PREPARE → EXECUTION/PROVIDER
             → RESULT → AUDIT_FINALIZATION → DTO
```

El ingreso HTTP es REQUEST; el primer evento del contrato es PREVIEW. Si falla PREPARE, la fuente no se invoca. Si falla RESULT/finalización, no se entrega el snapshot. La identidad/rol se resuelve en tabla fixture del servidor; el cliente no puede elevar rol. El sink es in-memory, solo desarrollo; no se conecta al ledger durable.

## Ejecución manual (no iniciada)

Puerto fijo por defecto: `8765`; opcionalmente `--port` solo cambia el puerto, nunca el host. Para desarrollo aislado:

```text
TRACCAR_MANAGER_DEV_API=1 python3 -m api.dev_http_dashboard_v1 --port 8765
```

No se inició el `main()` durante esta fase, ni se abrió un puerto externo. Las pruebas construyen una instancia temporal en puerto efímero y la cierran. El sandbox de validación no permitió conectar un cliente TCP a su propio listener loopback; por eso las pruebas de ruta ejercitan el handler HTTP con un socketpair local y dirección peer loopback simulada. Esto valida routing/headers/auditoría/DTO, pero no sustituye una prueba TCP real en un entorno de desarrollo autorizado.

## Pruebas

`tests/test_dev_http_dashboard_v1.py` comprueba el bind IPv4 loopback, endpoint y DTO, identidad/rol, operación/path allowlisted, request exacto, proveedores fixture, proveedor ausente/no allowlisted/erróneo, auditoría fail-closed antes y después de leer, métodos no GET, privacidad y ausencia de imports/ejecución de SQL, shell, systemd, Worker o Scheduler. Solo utiliza biblioteca estándar, fixtures y sinks en memoria. El servidor/listener temporal se cierra al terminar la suite; no se deja thread ni proceso persistente.

No se consultó ni modificó producción, Apache, Traccar, MySQL, configuración o servicios.
