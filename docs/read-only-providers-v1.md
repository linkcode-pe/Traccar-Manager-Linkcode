# Proveedores read-only v1 — fuentes seguras y pendientes

**Alcance:** preparación aislada de proveedores. Se conserva la web existente. No se ejecutó ningún proveedor contra el host de producción, no se conectó MySQL, no se consultó systemd ni Traccar, y no se creó una API HTTP. No se instalaron paquetes en el servidor.

## 1. Componentes creados

- `api/providers/system_metrics_v1.py`: proveedor de métricas del sistema y fuente estándar opcional de solo lectura, con rutas fijas `/proc/stat`, `/proc/meminfo` y filesystem `/` (`statvfs`). No usa root, shell, subprocess, base de datos ni ruta elegida por request. La clase de fuente está definida, pero no se invocó.
- `api/providers/traccar_status_v1.py`: contrato/adaptador desde un registro de estado tipado y fijo a `GeneralStatusDTO`. No contiene fuente systemd, no importa ni ejecuta `worker/operations/traccar_status.py`, y acepta solo un `source_id` configurado y allowlisted. Las pruebas usan fixture.
- `api/providers/__init__.py`: marcador del paquete.
- `tests/test_readonly_providers_v1.py`: pruebas unitarias con datos en memoria, fuente fixture y sink mock.
- `docs/read-only-providers-v1.md`: evaluación de fuentes, datos y permisos.

No se modificaron `api/read_only_dashboard_v1.py`, `api/dashboard_status_contract.py`, el dispatcher, el ledger, la web ni configuración del servidor.

## 2. Separación y límite de auditoría

```text
DTO / contrato existente → provider de recurso → Data Source inyectado
                                    ↑
         ReadOnlyDashboardProvider autentica/RBAC/audita antes y después
```

Los providers de recurso se deben invocar desde el borde `ReadOnlyDashboardProvider`, luego de PREVIEW, autorización RBAC y `AUDIT_PREPARE/EXECUTION`; el borde registra RESULT y `AUDIT_FINALIZATION` y retiene la respuesta si falla la auditoría. Las pruebas incluyen una composición mock que confirma que las fuentes no se llaman antes de `AUDIT_PREPARE` y que un fallo de auditoría bloquea ambas lecturas.

El `ReadAuditSink` actual sigue siendo un port y el test usa un sink en memoria. No se añadió puente al ledger durable ni se amplió la allowlist del dispatcher. Antes de producción se necesita una fase autorizada para el bridge compatible con audit-model v1 y recibos durables. No se registran valores de DTO, CPU/memoria, estado bruto, coordenadas, SQL, rutas, credenciales ni excepciones en eventos.

## 3. Servicio Traccar y aplicación

**Resultado:** `PENDING_PROVIDER` en esta fase. El adapter existente de `traccar.status` tiene allowlist fija (`LoadState`, `ActiveState`, `SubState`, `UnitFileState`, `Result`) y target `traccar.service`, pero usa systemd/subprocess. La instrucción actual prohíbe integrarlo ahora; no hay fuente real conectada ni ejecutada. `TraccarStatusProvider` acepta únicamente un `TraccarStatusRecord` ya obtenido por una fuente futura autorizada, con timeout fijo de 5 s y source ID allowlisted.

Campos mapeados en un fixture: state, substate, load state, unit-file state, result y timestamp. **Uptime, versión y overall health quedan `PENDING_PROVIDER`**: no se derivan de `ActiveState`, ni se leen `/opt/traccar`, ni se hacen requests a Traccar. No admite `unit`, service name, comando o propiedades elegidas por el usuario.

Errores internos estables: `TRACCAR_STATUS_PENDING_PROVIDER`, `TRACCAR_STATUS_SOURCE_NOT_ALLOWED`, `TRACCAR_STATUS_SOURCE_UNAVAILABLE`, `TRACCAR_STATUS_DATA_INVALID`, `TRACCAR_STATUS_TIMEOUT`, `TRACCAR_STATUS_INTERNAL_ERROR`. Los mensajes no incluyen detalles de origen.

Permisos: ninguno creado. Una futura fuente systemd deberá ser la operación existente fija y pasar por el Worker/auditoría, con identidad y permisos aprobados en fase separada. No crear un helper ni bypass.

## 4. CPU, memoria y disco

**Resultado:** proveedor seguro preparado, no ejecutado. `ProcfsSystemMetricsSource` usa exclusivamente la primera línea agregada `cpu` de `/proc/stat`, `MemTotal`/`MemAvailable` de `/proc/meminfo` y `statvfs("/")`. CPU% se calcula de dos muestras consecutivas; memoria usada = total − disponible; disco libre usa bloques disponibles para usuario. No se devuelve hostname, lista de procesos, mount path seleccionable, contenido completo de procfs ni otras entradas.

- El timeout es fijo y máximo de 2 s; intervalo de muestreo CPU fijo de 0,1 s.
- Las lecturas procfs/statvfs son estándar y no requieren root en una configuración Linux usual; este permiso **no se comprobó ejecutando la fuente** en producción.
- Los tests del provider solo usan `FixtureMetricsSource`; parsers reciben strings fixture y no abren procfs.
- En caso de error o métricas inconsistentes, el provider falla con un código estable; no sustituye con ceros ni valores anteriores.

Errores internos: `METRICS_PROVIDER_PENDING`, `METRICS_SOURCE_NOT_ALLOWED`, `METRICS_SOURCE_UNAVAILABLE`, `METRICS_DATA_INVALID`, `METRICS_TIMEOUT`, `METRICS_INTERNAL_ERROR`.

## 5. Dispositivos, posiciones y retención

- **Dispositivos:** no se creó Data Source. `DeviceSummaryDTO` queda `PENDING_PROVIDER`. Futuro proveedor dedicado de agregados allowlist con acceso SQL read-only mínimo; no MySQL en esta fase. No entregar uniqueid/nombres por defecto.
- **Posiciones:** no se creó Data Source. `PositionSummaryDTO` queda `PENDING_PROVIDER`; únicamente agregados mínimos. Coordenadas, direcciones, uniqueid y filas individuales quedan prohibidos en estos DTOs. Cualquier detalle requerirá autorización/contrato aparte.
- **Retención:** no se creó Data Source. `RetentionStatusDTO` queda `PENDING_PROVIDER` para configuración, cutoff y última ejecución. No leer archivos de estado, consultar DB ni ejecutar scripts/timers.

El scaffold existente `pending_snapshot()` representa secciones pendientes sin inventar valores. Códigos API estables de indisponibilidad ya definidos en `api/read_only_dashboard_v1.py`: `API_PROVIDER_UNAVAILABLE`, `API_DATA_UNAVAILABLE`, `API_SOURCE_NOT_ALLOWED`, `API_TIMEOUT`, `API_AUDIT_UNAVAILABLE` y `API_INTERNAL_ERROR`.

## 6. Allowlist y datos prohibidos

| Provider | Permitido | Prohibido / no implementado | Timeout | Estado de fuente |
|---|---|---|---:|---|
| Métricas host | CPU agregado, RAM total/usada, disco total/libre de `/` | paths de request, procesos, shell, paquetes externos | 2 s | fuente procfs definida; no ejecutada |
| Status Traccar | 5 propiedades tipadas y timestamp desde fuente inyectada fija | service/unit selector, `systemctl` desde este módulo, uptime/version/health inferidos | 5 s | fixture solamente; integración real pendiente |
| Dispositivos | conteos agregados si se autoriza | SQL libre, identificadores y datos detallados | pendiente | sin provider |
| Posiciones | conteos/estado mínimo si se autoriza | coordenadas, direcciones, IDs y filas | pendiente | sin provider |
| Retención | configuración/cutoff/último estado con fuente aprobada | SQL, scripts, timers y filesystem arbitrario | pendiente | sin provider |
| Versión Traccar | ninguno en esta fase | leer instalación o ejecutar comandos | pendiente | `PENDING_PROVIDER` |

No hay selección arbitraria de source ID desde request. El allowlist de código se pasa desde configuración confiable. Cada proveedor exige un source concreto autorizado; si no existe, retorna error pendiente, no datos fabricados.

## 7. Pruebas y cobertura

`tests/test_readonly_providers_v1.py` cubre parseo fixture de CPU/memoria, cálculos y validación; DTOs y mapeo de métricas/status; fuente ausente/no allowlisted, timeout, fallos y datos inválidos; timeout fijo; ausencia de parámetros de ruta/servicio; estado pendiente de MySQL/posiciones/retención; y composición mock con auditoría fail-closed. Ninguna prueba instancia/llama el método de lectura real de `ProcfsSystemMetricsSource`; no usa systemd, MySQL, Traccar, shell, scripts ni archivos de producción.

La clase procfs está preparada pero no habilitada por configuración de Manager, servicio, endpoint o web. Requiere revisión posterior antes de cualquier invocación. La fuente Traccar queda `PENDING_PROVIDER` hasta autorizar el puente al adapter/Worker; los demás providers quedan pendientes de fuente y permisos específicos.
