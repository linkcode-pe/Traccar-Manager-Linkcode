# Centro de mantenimiento — Fase 4 v1

## Alcance inicial

La primera operación nueva es **preview de retención de logs**. Es deliberadamente no destructiva: clasifica qué logs históricos serían candidatos y calcula cantidad/bytes, pero no elimina ni modifica archivos.

Política inicial:

- directorio de producción previsto: `/opt/traccar/logs`;
- retención predeterminada: **90 días**;
- solo nombres `tracker-server.log.YYYYMMDD`;
- `tracker-server.log` activo nunca puede ser candidato;
- symlinks no son candidatos;
- el directorio debe ser absoluto, existente, directorio real y no symlink;
- rango de retención permitido por el núcleo: 30–3650 días;
- cutoff estricto: solo `mtime < cutoff`;
- resultado determinista con nombre, ruta, bytes y mtime UTC;
- ninguna acción destructiva ocurre durante preview.

## Secuencia de entrega

1. Núcleo puro de preview + pruebas (este incremento).
2. Contrato Worker/RBAC/auditoría para `maintenance.logs.preview`.
3. Endpoint y tarjeta del dashboard.
4. Validación read-only contra producción.
5. Diseñar `maintenance.logs.execute` por separado, ligado criptográficamente al preview/confirmación y con rollback/evidencia apropiados.

No se reutiliza directamente el script destructivo `traccar_log_retencion_30d.sh` desde la web. Ese script queda como referencia histórica hasta que la ejecución controlada tenga contrato propio.

La retención de posiciones/MySQL permanece fuera de este incremento y no se toca.

## Incremento 2 — Worker + RBAC + auditoría

`maintenance.logs.preview` ya está definido como operación del protocolo UDS del Worker. Acepta únicamente `retention_days` entre 30 y 3650, exige el rol servidor `maintenance.logs.preview` y usa el directorio fijo `/opt/traccar/logs`; el cliente no puede suministrar rutas.

La operación recorre el flujo auditado de nueve eventos (request, validation, preview, autorización RBAC_READ, audit prepare, result y finalization) sobre el ledger compartido. Se añadió un recibo de finalización genérico verificable para operaciones read-only que no tienen el schema específico de systemd.

Este incremento **no está desplegado en producción y no expone todavía una ruta HTTP ni botón en el dashboard**. Tampoco existe operación de borrado. El siguiente incremento será el cliente Manager/UDS y la API/UI de preview, manteniendo la operación no destructiva.

## Incremento 3 — Manager API y dashboard de Preview

El Manager incorpora el puente `Manager -> UDS -> Worker` para `maintenance.logs.preview`, verifica el recibo contra el ledger compartido antes de devolver datos y expone `GET /api/maintenance/logs/preview` únicamente a sesiones con el rol correspondiente. El dashboard añade un Centro de mantenimiento con retención configurable (30–3650 días), cantidad de candidatos, bytes potencialmente recuperables y listado de archivos candidatos.

La interfaz usa exclusivamente nodos de texto para representar nombres/fechas devueltos por el Worker y conserva explícitamente `destructive_action_performed=false`. **No existe endpoint, botón ni operación de borrado en este incremento.** Este código permanece en la rama Phase 4 y aún no está desplegado en producción.
