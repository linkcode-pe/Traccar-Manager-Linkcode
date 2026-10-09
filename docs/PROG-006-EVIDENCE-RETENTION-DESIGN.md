# PROG-006 — Política de retención de evidencias (propuesta, no desplegada)

## Incidente observado

El 2026-10-09 el runner completó correctamente la batería aislada, pero el recorder devolvió código 6 porque el checklist de PROG-006 ya alcanzó su máximo de 20 cadenas de evidencia. La ejecución quedó como `record_failed`; no se descartaron evidencias y no se marcó ninguna tarea como verificada.

## Separación de responsabilidades

- **Checklist:** conservar las referencias ya registradas (máximo 20); no truncar, reordenar ni sobrescribir evidencias históricas por el simple hecho de ejecutar pruebas.
- **Bitácora de ejecuciones:** añadir una tabla SQLite independiente y de solo anexado lógico con `event_id` único, `task_id`, `source_sha256`, ruta relativa de reporte bajo `docs/test-runs/`, SHA256 completo del reporte, resultado y fecha UTC. Cada fila identifica una ejecución comprobable sin saturar el checklist.
- **Transacción:** registrar evento de progreso y metadatos de evidencia en una única transacción. Si la operación falla, no debe existir un evento de éxito huérfano. La repetición del mismo `event_id` debe ser idempotente; conflicto de contenido debe rechazarse.
- **Integridad:** no confiar en código de salida proporcionado por cliente externo; verificar reporte regular, ruta permitida, hash, tamaño y resultado real del ejecutor. No aceptar symlinks. No modificar MySQL ni Traccar Core.
- **Retención:** no purgar registros ni archivos automáticamente. Cualquier archivado futuro debe preservar ruta, digest, copia verificable y respaldo restaurable, con aprobación administrativa previa.
- **Visualización:** exponer conteos y referencias recientes a usuarios autorizados, con paginación y sin rutas absolutas o información sensible.

## Plan de implementación segura

1. Añadir migración idempotente de la tabla y pruebas sobre SQLite temporal.
2. Introducir operación transaccional de inserción de evidencia sin alterar `ingest_event` ni el límite del checklist.
3. Migrar el recorder para utilizar esa operación solo después de validar una ejecución aprobada; conservar idempotencia y rechazar cambios de estado `verified`.
4. Ejecutar pruebas de saturación (>20), duplicados, conflictos, transacciones fallidas, reportes manipulados y concurrencia en laboratorio.
5. Respaldar la base SQLite productiva, desplegar selectivamente, verificar `PRAGMA integrity_check`, y realizar una ejecución controlada sin borrar evidencia existente.

**Estado:** diseño documentado. No autoriza incrementar el límite del checklist ni aplicar una migración a producción sin completar las pruebas.
