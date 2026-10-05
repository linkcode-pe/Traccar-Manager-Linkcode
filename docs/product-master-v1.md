# Traccar Manager Linkcode — Mapa Maestro de Producto V1

## Norte único
Traccar Manager Linkcode es una plataforma/plugin web reutilizable para administrar Traccar de forma controlada. Centraliza mantenimiento, datos y administración Traccar; no es consola Linux, phpMyAdmin ni shell remoto. V1 debe instalarse también en servidores Traccar externos mediante asistente.

## Principios no negociables
- GitHub es referencia del código; producción no es el entorno de desarrollo.
- Manager y Traccar permanecen separados.
- Web nunca recibe shell, SQL ni rutas arbitrarias para ejecutar.
- Cada operación tiene schema, RBAC, allowlist, Worker y auditoría.
- Lectura y escritura usan permisos distintos.
- Destructivas: DETECTAR -> PREVIEW -> CLASIFICAR -> CONFIRMAR -> RESPALDAR -> REVALIDAR -> EJECUTAR -> VERIFICAR -> AUDITAR.
- No existe SQL libre ni explorador/borrador arbitrario de filesystem.
- Manager es la única interfaz y plano de control del producto. El antiguo Panel queda retirado. Su lenguaje visual oscuro azul-negro, tarjetas compactas, acento cian y responsive se conserva dentro de Manager, sin dependencia de `/panel`.
- Secretos/backups/datos privados no entran a Git.
- Ninguna función debe depender de homecargps.com, IDs locales o una única cuenta.

## Estados estándar
`PLANNED` -> `READ_ONLY` -> `PREVIEW` -> `PREPARED` -> `ENABLED`. `DISABLED` representa una capacidad implementada pero apagada por política. La UI puede mostrar módulos futuros solo indicando su estado real.

## Módulos V1
### M0 — Core, identidad y seguridad
Auth, sesiones, RBAC, UDS, Worker no-root, auditoría hash-chain, receipts, health y feature gates. Estado: baseline operativo.

### M1 — Dashboard operativo
Salud Manager/Worker/Traccar, almacenamiento, accesos, alertas y resumen. No consola del SO. Estado: READ_ONLY parcial.

### M2 — Centro de Mantenimiento
Logs Traccar; archivos temporales/basura únicamente allowlisted; almacenamiento; historial de tareas y rollback cuando aplique. Sin rutas arbitrarias ni rm genérico. Estado: logs en PREVIEW productivo.

### M3 — Datos e historial Traccar
Tamaños/estadísticas, antigüedad/volumen, preview de retención y limpieza especializada con límites, backup y confirmación. `tc_positions` permanece fuera de alcance hasta sus gates. Sin editor SQL. Estado: PLANNED.

### M4 — Usuarios Traccar
Listar, buscar e inspeccionar; luego crear, editar, habilitar/deshabilitar y relaciones permitidas con RBAC separado. Estado: PLANNED.

### M5 — Vehículos/dispositivos
Listar/buscar, inspeccionar identidad/estado y administrar asignaciones permitidas. Estado: PLANNED.

### M6 — Relaciones Traccar
Relaciones usuario-dispositivo, grupos y recursos necesarios, reutilizando contratos M4/M5. Estado: PLANNED.

### M7 — Auditoría, tareas e historial
UI para quién solicitó, preview, autorización, resultado, receipt, errores y rollback. Backend técnico parcial; UI PLANNED.

### M8 — Configuración Manager
Retención, módulos, roles, configuración no secreta, diagnóstico y feature gates. Estado: PLANNED.

### M9 — Instalador y portabilidad
Detectar entorno/Traccar, validar requisitos, configurar conexión permitida, crear identidades/runtime, instalar servicios, crear admin inicial, ejecutar gates y ofrecer rollback. Estado: PLANNED.

### M10 — Release, upgrade y rollback
Versionado, paquete, migraciones Manager, compatibilidad Traccar, backup previo, upgrade y rollback. Estado: PLANNED.

## Permisos objetivo reservados
- Dashboard: `dashboard.read`, `traccar.status.read`.
- Logs: `maintenance.logs.preview` -> `maintenance.logs.prepare` -> `maintenance.logs.execute`.
- Files: `maintenance.files.read/preview/prepare/execute`.
- Datos: `traccar.data.read`, `traccar.data.retention.preview/prepare/execute`.
- Usuarios: `traccar.users.read/create/update/disable`.
- Dispositivos: `traccar.devices.read/create/update/disable`.
- Relaciones: `traccar.relations.read/update`.
- Auditoría: `audit.read`.
- Config: `manager.config.read/update`.
Su documentación no los habilita.

## Gate de activación
`UI/SKELETON -> READ_ONLY -> PREVIEW (si muta) -> PREPARED -> ENABLED`. Para ENABLED: tests, RBAC fail-closed, schema allowlisted, auditoría durable, idempotencia cuando corresponda, backup/rollback, prueba aislada, despliegue controlado y verificación post-deploy.

## Orden de construcción V1
1. Congelar mapa maestro y navegación modular.
2. Completar M2: logs end-to-end y luego archivos allowlisted.
3. M4 Usuarios: READ_ONLY y luego escrituras controladas.
4. M5/M6 dispositivos y relaciones.
5. M3 datos/retención Traccar, después de madurar el patrón de mutación.
6. M7 auditoría/tareas y M8 configuración.
7. M9 instalador y eliminación de supuestos locales.
8. M10 release/upgrade/rollback y prueba de instalación limpia.

## Definición de V1 terminada
Una instalación Traccar compatible puede instalar Manager desde cero, iniciar sesión, ver salud, ejecutar mantenimiento permitido con auditoría/rollback, administrar usuarios/dispositivos/relaciones dentro del alcance, gestionar retención Traccar segura, revisar historial y actualizar/desinstalar Manager sin comprometer Traccar.

## Fuera de alcance V1
Shell web, phpMyAdmin/SQL libre, filesystem arbitrario, administración general Linux, modificar binarios de Traccar y destructivas masivas sin preview/confirmación/revalidación/auditoría.

## Decisión de consolidación — 2026-10-05
- `/manager/` es la única interfaz operativa.
- `/panel/` queda retirado y redirige a `/manager/`; su telemetría programada queda deshabilitada.
- Los jobs legacy de retención de logs 30d y base de datos 90d quedan deshabilitados. Sus capacidades deberán migrarse a operaciones Manager con RBAC, preview, auditoría y gates antes de volver a activarse.
- No se crearán nuevos scripts autónomos de administración fuera de Manager/Worker.
- Los artefactos legacy pueden conservarse temporalmente solo como rollback hasta completar su retirada; no son autoridad ni runtime activo.

La auditoria de consolidacion esta en `docs/panel-to-manager-audit-2026-10-05.md`. El legado no se porta literalmente; cada capacidad entra por su modulo Manager y sus gates.

## Estado de referencia — 2026-10-05
Core seguro activo. Phase 4 está en `phase4/maintenance-center`. Preview de logs está desplegado, no destructivo y con métricas estilo `/panel`. M2 `maintenance.logs.prepare` ya tiene core y gate Worker/RBAC/auditoría en desarrollo; todavía no existe borrado real. Siguiente frontera: puente Manager/UI de preparación, manteniendo `maintenance.logs.execute` inexistente.
