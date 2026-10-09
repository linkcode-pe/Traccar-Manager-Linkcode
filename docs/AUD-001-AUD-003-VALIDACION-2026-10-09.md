# AUD-001 / AUD-003 — Validación aislada (2026-10-09)

## AUD-001: línea base y pruebas
- Producción: Traccar y Traccar Manager activos al momento de la comprobación.
- Se identificaron ocho rutas modificadas o no versionadas respecto al HEAD productivo; queda pendiente reconciliarlas con GitHub.
- La primera ejecución aislada falló: 5 tests fallidos y 13 errores de inicialización por intentar acceder al SQLite productivo desde pruebas no privilegiadas.
- Corrección aislada: `TRACCAR_MANAGER_PROGRESS_DB` configurable, y runner asigna `$LAB/progress.sqlite3`.
- Repetición de la batería completa en el laboratorio: exit code 0, nueve pruebas omitidas; no equivale a pruebas autenticadas en producción.

## AUD-003: control de acceso
- `manager.progress.authorized()` deniega principal sin permisos y principal con `dashboard.read` solamente.
- Principal con `development.progress.manage` puede consultar catálogo en base de datos aislada (77 tareas).
- GET HTTP anónimo `/manager/api/progress`: 401; página anónima `/manager/progress`: 303 hacia autenticación.
- Las rutas POST del checklist comprueban sesión, permiso específico, Origin y cabecera de solicitud; pendiente prueba HTTP autenticada de rol insuficiente y validación de CSRF, idempotencia y revocación.
- No se han realizado operaciones destructivas ni se han utilizado credenciales de usuarios.

## Estado
AUD-001 y AUD-003 permanecen en pruebas / desarrollo hasta completar los criterios y documentar aceptación. Ninguna tarea se marca verificada por esta revisión parcial.
