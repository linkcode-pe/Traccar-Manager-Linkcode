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
