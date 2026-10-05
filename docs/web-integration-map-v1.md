# Mapa de integración de la web existente — preparación aislada

**Estado:** análisis estático y contrato de datos de prueba; no se publicó ni ejecutó ningún componente. La copia en `web/` se conserva como base de interfaz, sin rediseño. La raíz Git se verificó como `/opt/traccar-manager/`.

## 1. Verificación y comparación

La comparación de integración se realizó en modo de solo lectura sobre la raíz de proyecto prevista `/opt/traccar-manager/`. Se listaron siete entradas en cada árbol: el directorio `assets/` y seis archivos ordinarios. Los seis archivos coincidían byte por byte; no había cambios de interfaz entre la fuente original y la copia Manager.

| Ruta relativa | SHA-256 (original y Manager) | Bytes |
|---|---|---:|
| `index.php` | `a9604391f2365d41c14e79e821830ebf834edf8208efb28250b10e8badbaf332` | 27.854 |
| `login.php` | `f79578495d26641304b998143112746e0a3db988b918542deb31997a9fa7a837` | 3.836 |
| `logout.php` | `6580f1e059097c1981adc5996b1f59f49124b9410d0b93882005b06a58dac9fa` | 493 |
| `login.css` | `2edd696b9e173357b2cfc2f2db3f8995f23222b76f994ee964058f8870b78ee0` | 3.398 |
| `assets/app.js` | `7164a2f3d88d2f5785acfe4823dc9f4193623236ead2788f2a0a867ba465e1c2` | 319 |
| `assets/style.css` | `57e42e1249ecba7967911b5f6f51d29534eed6ecf9711b8751e81571254ba4a` | 8.985 |

Rutas: fuente `/var/www/html/panel/`; copia `/opt/traccar-manager/web/`. `login.php` ofrece el formulario y procesa autenticación; `logout.php` cierra sesión; `index.php` es el dashboard; las hojas de estilo y `app.js` dan formato y recargan la página. No se reemplazó ni modificó ninguno de esos archivos.

## 2. Inventario funcional

Convención de conteo: dos pantallas (`/panel/login.php` y `/panel/`) y doce funciones/rutas identificables: diez de lectura/recarga y dos de control de sesión. El endpoint de logout no es una acción operativa del servidor. La tabla de posiciones contiene datos sensibles de ubicación e identificadores y requiere autorización RBAC y minimización en cualquier API futura.

| ID | Nombre | Ruta / archivo | Tipo | Información/efecto actual | Destino conceptual |
|---|---|---|---|---|---|
| WEB-01 | Login | `/panel/login.php`, `web/login.php` | Control de autenticación | POST de usuario/contraseña, CSRF, sesión; no actúa sobre Traccar | WEB/API de autenticación |
| WEB-02 | Logout | `/panel/logout.php`, `web/logout.php` | Control de autenticación | Invalida la sesión/cookie | WEB/API de autenticación; no Worker |
| F-01 | Estado MySQL | `web/index.php` | `READ_ONLY` | Indicador de conexión; no expone credenciales | API |
| F-02 | Estado Traccar | `web/index.php` | `READ_ONLY` | Lee snapshot local de estado; muestra estado/subestado y timestamps/reinicios | API; Worker/adaptador `traccar.status` solo si se solicita una lectura fresca |
| F-03 | Retención de posiciones 90d | `web/index.php` | `READ_ONLY` | Telemetría de último ciclo, inicio/fin, último conteo por dispositivo y actualización | API de estado |
| F-04 | Retención de logs 30d | `web/index.php` | `READ_ONLY` | Último estado, mensaje, inicio/fin, resultado, archivos/bytes borrados y cutoff registrado | API de estado |
| F-05 | Inventario/candidatos de logs | `web/index.php` | `READ_ONLY` | Cuenta nombres `tracker-server.log.YYYYMMDD`, compara `filemtime` con cutoff y estima candidatos; no elimina archivos | API read-only o snapshot; no convertir el cálculo en acción |
| F-06 | Espacio de disco | `web/index.php` | `READ_ONLY` | Espacio libre/usado/total del filesystem raíz | API de estado/snapshot |
| F-07 | Conteo de dispositivos | `web/index.php` | `READ_ONLY` | Total, habilitados y deshabilitados | API con consulta allowlist y rol apropiado |
| F-08 | Métricas de posiciones | `web/index.php` | `READ_ONLY` | Filas InnoDB aproximadas, data/index bytes, y conteo >90d de posiciones referenciadas | API/proveedor read-only acotado; validar costo antes de habilitar |
| F-09 | Posiciones actuales | `web/index.php` | `READ_ONLY` | Hasta 200 dispositivos: nombre, uniqueid, status, tiempos, coordenadas, velocidad, curso y dirección | API; restringir campos/filas y auditar acceso |
| F-10 | Actualizar | botón `data-action="refresh"`, `web/assets/app.js` | `READ_ONLY` | Recarga la página; no crea job ni invoca operación | WEB; futuro refresh GET a API |

No hay función `PREVIEW`, `AUTHORIZED_ACTION` ni `DESTRUCTIVE_ACTION` en la web. El conteo de candidatos de logs no es una preview de borrado: no produce un alcance aprobado, preview ID/hash ni confirmación y nunca borra. Tampoco hay formularios de restart/start/stop, SQL de escritura ni endpoints operativos.

## 3. Datos y dependencias actuales

### Consultas SQL (lectura estática; no se ejecutaron)

`index.php` crea PDO con la identidad esperada `panel_readonly` y contiene cuatro consultas constantes `SELECT`: (1) total/habilitados/deshabilitados desde `plataforma.tc_devices`; (2) `TABLE_ROWS`, `DATA_LENGTH`, `INDEX_LENGTH` de `information_schema.tables` para `tc_positions`; (3) `COUNT(*)` de posiciones >90 días unidas solo a `tc_devices.positionid`; (4) hasta 200 posiciones actuales unidas por `d.positionid = p.id`, ordenadas por nombre/id. No aparecen `INSERT`, `UPDATE`, `DELETE`, DDL, shell ni llamadas a `systemctl` en la interfaz. El conteo y el listado no se midieron en esta fase.

### Archivos y recursos externos

Estos recursos se identificaron por las rutas literales de los archivos PHP. Su contenido no se abrió ni se copió; se consideran dependencias externas protegidas: ` /etc/traccar-panel/session_guard.php`, `/etc/traccar-panel/auth.php` y `/etc/traccar-panel-db.php`. No se accedió a la base de datos ni a archivos de estado.

| Recurso externo referenciado | Uso que declara el código | Tratamiento en esta fase |
|---|---|---|
| `/etc/traccar-panel/session_guard.php` | Control de sesión/autenticación del dashboard | Dependencia externa; contenido no leído |
| `/etc/traccar-panel/auth.php` | Usuario/hash para login | Dependencia externa; contenido no leído |
| `/etc/traccar-panel-db.php` | DSN/identidad/opciones PDO | Dependencia externa; contenido no leído |
| `/var/lib/traccar-retencion-90d/status` | Allowlist de telemetría de retención | Ruta identificada; archivo no leído |
| `/var/lib/traccar-log-retencion-30d/status` | Allowlist de telemetría de logs | Ruta identificada; archivo no leído |
| `/var/lib/traccar-panel-status/status` | Snapshot del estado Traccar | Ruta identificada; archivo no leído |
| `/opt/traccar/logs/tracker-server.log.YYYYMMDD` | Conteo y estimación por nombre/mtime/tamaño | Directorio/archivos no inspeccionados |
| Filesystem `/` | `disk_free_space`/`disk_total_space` en la página | No consultado |

El PHP abre directamente MySQL y filesystem al renderizar. Aunque las operaciones observadas son de lectura, ese acoplamiento debe moverse detrás de API/proveedores allowlist antes de que la web sea una interfaz Manager. La vista de posiciones revela `uniqueid`, coordenadas y direcciones; exigir RBAC, límites de filas y política de minimización. `panelLog()` escribe mensajes de excepción al error log cuando falla una consulta; no contiene una llamada a comandos del sistema.

## 4. Integración propuesta con Manager

Mantener HTML, CSS, login y estructura visual existentes como base; sustituir gradualmente las lecturas PHP directas por DTO de API. La Web no tendrá credenciales SQL Traccar, acceso a archivos de estado/logs ni permisos de sistema.

| Componente | Responsabilidad futura | Límite |
|---|---|---|
| WEB | Conservar pantallas y presentar DTO; refresh solicita datos a API | Sin SQL, shell, filesystem de producción ni invocación de helpers |
| API | Autenticación/RBAC, agregados allowlist, DTO de dashboard y request/job para operaciones | No ejecuta comandos, acciones destructivas ni consultas arbitrarias |
| SCHEDULER | Crear ocurrencias/jobs solo para periodicidad aprobada | No ejecuta handlers ni scripts; no hace falta para el refresh manual |
| WORKER | Ejecutar jobs allowlist después de preview, autorización aplicable y audit prepare | No root; sin SQL arbitrario ni scripts de referencia |
| ADAPTER/HELPER | `worker/operations/traccar_status.py` es el adaptador fijo para `traccar.service`; opera únicamente dentro del job permitido | En esta fase se usa solo como mock. Un helper privilegiado de borrado/servicio no existe y requeriría fase propia |
| AUDIT LEDGER | Registrar request, validation, preview, autorización RBAC, `EXECUTION_STARTED` durable, resultado y finalización | Si falla el append obligatorio, no ejecutar. La autorización no ejecuta por sí sola |

El contrato actual del status acepta las propiedades `LoadState`, `ActiveState`, `SubState`, `UnitFileState`, `Result` y `observed_at_utc`. La página existente consume además `active_enter_timestamp`, `exec_main_start_timestamp` y `n_restarts` de otro snapshot; esos campos no los entrega el adaptador allowlist actual. No inventarlos ni buscarlos fuera de la allowlist: una futura tarjeta debe limitarse a datos respaldados por el contrato o definir una fase aparte para ampliar el esquema. `ActiveState=active` solo es estado systemd, no salud HTTP/aplicativa/DB.

La fase define `AUDIT_COMMIT` de negocio como el cierre existente `AUDIT_FINALIZED`; no añade un evento nuevo ni cambia el modelo del ledger. Para retenciones/borrados futuros, primero una preview exacta, autorización humana ligada a ella y una fase de ejecución independiente. Limpiar logs podría necesitar un helper con filesystem estrictamente acotado; borrar posiciones requiere un handler/identidad de datos específicamente aprobados. No reutilizar el Worker general como root.

## 5. Contrato de vista y pruebas aisladas

`api/dashboard_status_contract.py` es un validador/mapeador puro para un resultado confirmado de `traccar.status`; no crea servidor, endpoint, conexión ni runtime API. `tests/test_web_dashboard_contract.py` atraviesa el dispatcher y ledger con un `AuditLedger` temporal y parchea `worker.operations.traccar_status.handle` con un stub. Nunca llama el handler real, `systemctl`, Traccar, DB, Apache ni los archivos de estado. El DTO contiene solo la allowlist existente y se etiqueta `systemd_unit_state_only`; no afirma salud de aplicación.

## 6. Clasificación de dependencias/operaciones

- **A — lectura local controlada:** solo para un backend/collector de confianza con allowlist y lectura acotada; no desde PHP Web futuro.
- **B — API:** login/RBAC y todos los datos sanitizados del dashboard.
- **C — Scheduler:** únicamente ocurrencias programadas de jobs que se aprueben en fase futura; no el botón refresh.
- **D — Worker:** `traccar.status` por el dispatcher con identidad no-root y audit; automatizaciones futuras solo tras fase/contrato.
- **E — Helper privilegiado:** ninguno para mostrar los datos actuales; requeriría decisión y aislamiento nuevos para una futura limpieza o gestión de servicios.
- **F — autorización humana:** ninguna acción de la web actual; sí sería obligatoria para borrar posiciones/logs o cualquier acción privilegiada futura. `traccar.status` usa RBAC, no aprobación humana por consulta.
- **G — prohibido en Web:** leer secretos, acceso SQL directo a Traccar, `systemctl`/shell, enumerar/leer logs arbitrarios, delete/retention, iniciar/detener/reiniciar Traccar.

## 7. Alcance y pendientes

No se abrió `/etc/...`, no se consultó MySQL, no se ejecutó PHP ni ningún script, no se accedió a systemd/Traccar/Apache en runtime, y no se cambió la web original. Los scripts bajo `scripts/` permanecen referencias intactas y sin ejecutar; los timers y servicios existentes no se consultaron ni modificaron.

Antes de una integración funcional faltan: contrato API autenticado y sus DTO/roles; fuente read-only aprobada para métricas `tc_devices`/`tc_positions`; política de acceso a datos sensibles; resolver la diferencia de schema del status; repositorio/cola Manager DB y Scheduler/Worker productivos; integración durable WORM/checkpoints independiente para auditoría; y fases separadas con autorización para cualquier helper/acción privilegiada. No se ha probado compatibilidad o rendimiento de queries en runtime.
