# Integración controlada Web/API read-only — diseño v1

## Alcance de esta fase

Precheck confirmado en `homecargps.com` (`161.132.49.117`), huella SSH autorizada, raíz Git `/opt/traccar-manager/`, rama `master`. Los seis hashes de `web/` coinciden con la referencia. El `git status` mostró los artefactos previos como untracked; no se hizo staging/commit. La consulta read-only de sockets no mostró listener en los puertos API conocidos (8765 ni el efímero 43419). No se inició ningún proceso.

Esta fase agrega contratos, pruebas y documentación de diseño. No se ejecutó autenticación real, proveedor real, HTTP, ledger, Dispatcher, Worker, systemd, Traccar, métricas del host, DB ni scripts.

## Análisis estático permitido de login/logout

- `web/login.php` usa `session_start`, `session_regenerate_id` y `password_verify`; recibe `username`, `password` y `csrf_token`; referencias estáticas a las claves de sesión `panel_authenticated`, `panel_login_time`, `panel_login_csrf` y `panel_user`. Incluye el módulo protegido `/etc/traccar-panel/auth.php`.
- `web/index.php` incluye `/etc/traccar-panel/session_guard.php`. No se leyó su contenido.
- `web/logout.php` inicia/termina la sesión y redirige a `/panel/login.php`.
- No se leyeron ni copiaron `/etc/traccar-panel/auth.php`, `/etc/traccar-panel/session_guard.php` ni `/etc/traccar-panel-db.php`; tampoco credenciales o secretos.

**Límite:** no se puede afirmar exactamente qué condiciones hacen válida una sesión del dashboard porque eso depende del `session_guard.php` protegido, ni determinar las reglas/identidades reales de `auth.php` sin leerlo. No se implementó autenticación real. El browser session/cookie, username/password y CSRF no deben reenviarse a la API.

## Contrato identidad → autenticación → RBAC → autorización

`api/identity_contract_v1.py` define `VerifiedIdentity(issuer, subject_id)` como assertion interna que solo podría crear un futuro adapter de autenticación después de validar la sesión. No contiene `roles`, cookie, contraseña, token ni campos enviados por cliente. El resolver de roles es servidor-side. Para la operación fija `dashboard.snapshot.read.v1`, se verifica el rol `dashboard.read`; la fachada recibe un `ActorContext` limitado a ese rol. Una operación distinta se rechaza y el cliente no puede asignar roles.

El mínimo que necesitaría la API es: issuer confiable, subject opaco/estable y verificación de que la sesión PHP existente está vigente; después, RBAC interno para `dashboard.read`. `panel_user` no se eleva automáticamente a rol ni se transmite como identidad final. No se eligió ni implementó todavía el mecanismo seguro Web→API para transportar esa identidad.

Errores estables reutilizados: `API_UNAUTHORIZED` (401), `API_FORBIDDEN` (403), `API_INVALID_REQUEST`, `API_PROVIDER_UNAVAILABLE`, `API_SOURCE_NOT_ALLOWED`, `API_TIMEOUT`, `API_AUDIT_UNAVAILABLE`, `API_DATA_UNAVAILABLE` y `API_INTERNAL_ERROR`.

## Proveedores — diseño y estado

`api/provider_readiness_v1.py` es solo catálogo estático y no hace I/O.

| Recurso | Estado | Diseño/fuente prevista | Restricciones |
|---|---|---|---|
| `traccar.service` | `PENDING_PRIVILEGED_PROVIDER` | Propiedades fijas del adapter `traccar.status`, timeout 5s, vía operación allowlisted | Requiere identidad Worker no-root y autorización runtime aún no concedidas; no crear usuario, permisos, sudoers o helper |
| Métricas | `PENDING_PROVIDER` | CPU agregado de `/proc/stat`, RAM de `/proc/meminfo`, disco raíz mediante `statvfs("/")`, timeout 2s | Implementación fuente estática existente; no se abrió `/proc`, no se llamó `statvfs` ni se ejecutó proveedor |
| Versión/health de app | `PENDING_PROVIDER` | Sin fuente no secreta aprobada | No leer instalación/configuración ni ejecutar comandos |
| Dispositivos | `PENDING_PROVIDER` | Contrato futuro de conteos `total/active/inactive` | Sin MySQL/SQL ni IDs por defecto |
| Posiciones | `PENDING_PROVIDER` | Conteos mínimos aprobables en otro alcance | Prohibidos coordenadas, direcciones, `uniqueid` y filas individuales |
| Retención | `PENDING_PROVIDER` | Contrato futuro para estado específico | No consultar status files, scripts, timers o DB; los DTO genéricos actuales no separan claramente retención 90d y logs 30d |

El adapter existente `worker/operations/traccar_status.py` especifica target fijo, `shell=False`, timeout y rechazo de ejecución como root. Se inspeccionó solo el código; no se ejecutó. El Dispatcher actual tiene una allowlist limitada y no se amplió.

## Puente de auditoría durable

`api/audit_bridge_contract_v1.py` fija el flujo API requerido:

```text
PREVIEW → AUTHORIZATION → AUDIT_PREPARE → EXECUTION
        → RESULT → AUDIT_FINALIZATION
```

Validar el mock actual no equivale a una escritura durable. La API `ReadAuditSink.append()` actual no devuelve recibo; el `AuditLedger` requiere más contexto (incluidos `job_id`, `parameters_hash`, actor/requester, target y fase) y produce/verifica `AppendReceipt`. El Dispatcher está allowlisted para una operación existente, no para una operación de lectura del snapshot.

Por tanto, no se conectó la API directamente a `AuditLedger.append()` ni se simuló un recibo durable. La ruta futura requiere diseñar y autorizar explícitamente el gateway/operación read-audit compatible con el Dispatcher, transiciones/eventos, scope RBAC_READ, recibos por fases y verificación final. Si falla PREPARE, no se ejecuta provider; si falla resultado/finalización o no hay recibo verificable, no se entrega éxito.

La fachada existente solo tiene idempotencia en caché de instancia. Para durabilidad se necesita una clave de scope `(operation, request_id, actor_subject)` y un almacenamiento/ledger durable con política de reintento verificable; no se afirma que eso exista hoy. Eventos solo contienen metadatos compactos, nunca DTO/valores, secretos, coordenadas, SQL, rutas internas ni excepciones.

## Contrato para la Web existente

Se mantiene la ruta prevista `GET /api/v1/dashboard/status` y el DTO JSON actual. `web/adapters/dashboard_api_errors_v1.py` es un mapping de presentación, sin llamadas HTTP ni cambios en la web:

- `AVAILABLE`: presentar el campo aprobado.
- `PENDING_PROVIDER`: mostrar “pendiente”; no sustituir por `0`, no inventar filas ni mostrar datos cacheados como actuales.
- 401 `API_UNAUTHORIZED`: seguir el flujo de login existente; no reenviar credenciales.
- 403 `API_FORBIDDEN`/`API_SOURCE_NOT_ALLOWED`: mostrar acceso denegado, sin elevar rol ni cerrar una sesión válida automáticamente.
- `API_PROVIDER_UNAVAILABLE`, `API_AUDIT_UNAVAILABLE`, `API_TIMEOUT`, error de transporte o interno: indicar temporalmente no disponible, no exponer detalles ni presentar caché como dato actual.
- 400 `API_INVALID_REQUEST`: solicitud rechazada; no reintentar automáticamente.

Campos consumibles: estado limitado del servicio; métricas de CPU/RAM/disco; agregados de dispositivos; agregados de posiciones; estado genérico de retención. En esta fase los proveedores reales quedan pendientes, por lo que la UI debe mostrar pendientes para datos no disponibles. La tabla de posiciones individuales, tarjetas específicas de retención y estado DB no se pueden poblar con los DTO/proveedores aprobados actualmente.

`web/index.php`, `web/login.php`, `web/logout.php`, `web/assets/app.js`, `web/assets/style.css` y `web/login.css` no se modificaron. No se hicieron llamadas HTTP.

## Tests y próxima autorización

`tests/test_controlled_integration_design_v1.py` usa fixtures/sinks en memoria para identidad, role resolver, allowlist, proveedores ausentes/no autorizados, errores de fuente, fallos de auditoría, idempotencia, privacidad, disponibilidad del UI y contratos de readiness. No toca ledger ni fuentes reales.

Futuras autorizaciones separadas necesarias: adapter de identidad confiable desde la sesión PHP (sin leer secretos), operación/gateway read-audit con recibos verificables, aprobación de identidad/permisos no-root para status Traccar, y autorización para ejecutar métricas en un entorno de desarrollo controlado. Ningún acceso DB/posiciones/retención está incluido.
