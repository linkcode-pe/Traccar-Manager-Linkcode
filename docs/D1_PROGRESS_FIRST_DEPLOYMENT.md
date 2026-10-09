# D1 — Centro de Desarrollo y Progreso: primer despliegue

**Fecha:** 2026-10-09  
**Estado:** Primera versión desplegada; pruebas de navegador con cuenta real y validación funcional completa pendientes.

## Alcance instalado
- Ruta web: `/manager/progress` (protegida por sesión y permiso `development.progress.manage`).
- API: `GET /manager/api/progress` y `POST /manager/api/progress`.
- Catálogo inicial: 31 tareas identificadas en el Plan Maestro, todas inicialmente pendientes por falta de evidencia de verificación.
- Filtros, búsqueda, edición de estados, evidencia obligatoria y documentación asociada.
- SQLite persistente: `/var/lib/traccar-manager-progress/progress.sqlite3`; tabla de historial para cambios de estado.
- Acceso autorizado únicamente al rol dedicado. El rol se aprovisionó en la cuenta administrativa existente, sin exponer contraseñas.

## Seguridad
- La sesión se resuelve en el servidor; el navegador no suministra identidad ni permisos.
- Lecturas no autorizadas: 401; sesiones sin el rol: 403.
- POST exige sesión autorizada, origen `https://homecargps.com` y encabezado `X-Requested-With`.
- El estado verificado requiere evidencia y documentación verificada o justificación «no aplica».
- El directorio de SQLite solo es accesible por el usuario del servicio; systemd permite escritura únicamente en esa ruta adicional.

## Pruebas y observaciones
- 26 pruebas de API/diseño existentes: OK.
- 15 pruebas de autenticación existentes: OK (1 omitida).
- Pruebas HTTP de sesión simulada: API 200 para rol autorizado, 403 para usuario sin rol, interfaz 200 para rol autorizado.
- Rutas externas sin sesión: 401; `/manager/health` y API oficial Traccar: 200.
- El primer reinicio falló por una operación bytes/str en la plantilla HTML; se corrigió y se verificó el servicio activo.
- **Pendiente:** prueba visual en navegador con sesión real, prueba POST extremo a extremo, restauración ensayada, ampliación del catálogo con criterios completos, auditoría enriquecida y documentación funcional.

## Archivos afectados
- `manager/web_app.py`
- `manager/auth/auth_store.py`
- `manager/progress.py`
- `manager/progress_page.py`
- `/etc/traccar-manager/auth-store.json` (permiso nuevo en la cuenta existente; no respaldar públicamente)
- `/etc/systemd/system/traccar-manager.service.d/50-progress-checklist.conf`
- `/var/lib/traccar-manager-progress/progress.sqlite3`

## Recuperación
Respaldo anterior: `/root/traccar-manager-deploy-backups/pre-prog001-20261009T052550Z.tar.gz`. El archivo de autenticación y las configuraciones systemd previas están respaldados en el mismo directorio con esa marca de tiempo. Para revertir, detener solo `traccar-manager`, restaurar archivos y configuración previos, quitar el drop-in nuevo, ejecutar `systemctl daemon-reload`, iniciar el servicio y verificar `/manager/health`. No borrar la base SQLite de avances; conservarla para recuperación. No modificar el servidor oficial Traccar.

## Próxima iteración
Completar pruebas de POST, navegación real, criterios de aceptación y dependencias por tarea, pruebas de respaldo/restauración y trazabilidad ampliada.


## PROG-006 — Actualización incremental (2026-10-09)
- Nueva API autenticada `POST /manager/api/progress/event` con `event_id`, `task_id`, `source`, `state`, `doc_state` y `evidence`.
- Tabla `progress_events` para idempotencia y trazabilidad, además del historial existente.
- El navegador refresca automáticamente la lista cada 15 segundos cuando la página está visible.
- Se registró el evento real `PROG-006` en desarrollo; **no se marcó verificado**.
- Pruebas HTTP aisladas: permiso, origen, idempotencia, persistencia y evidencia de verificación, aprobadas.
- Pendiente: integración con GitHub Actions y prueba visual real.


## Catálogo funcional ampliado — 2026-10-09
- 45 capacidades nuevas en 5 módulos, con identificadores TRC/MNT/WAP/ADM/DEV.
- Total del checklist: 77 tareas, incluidas 32 tareas técnicas anteriores.
- Migración no destructiva mediante INSERT OR IGNORE; estados y evidencias previos conservados.
- Fuente: `manager/progress_catalog.py`, documentada en Plan Maestro v2.5.
- No se realizaron operaciones de limpieza MySQL, cambios en Traccar oficial ni envíos WhatsApp.

## Especificaciones iniciales del checklist (2026-10-09)
- Se sustituyen 22 títulos técnicos genéricos por nombres legibles; las 77 tareas tienen título específico.
- Cada tarea muestra una descripción y tres criterios iniciales de aceptación (231 criterios en total).
- Los criterios son guías de revisión por módulo; **no** equivalen a pruebas ejecutadas ni certificación de implementación.
- Los estados, evidencias y porcentajes de verificación permanecen inalterados; el trabajo iniciado se muestra según su estado real.
- Pruebas aisladas: catálogo de 77 tareas, 231 criterios, conservación de estado e imposibilidad de inferir verificación.
