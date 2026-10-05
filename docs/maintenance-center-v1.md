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

## Incremento 4 — Validación HTTP/UI aislada

La ruta HTTP y la UI fueron ejercitadas en un `ManagerHTTPServer` efímero ligado exclusivamente a `127.0.0.1`, con sesión y proveedor ficticios. Se validó HTTP 200 para una sesión con `maintenance.logs.preview`, rechazo 401 sin sesión, rechazo de parámetros fuera de política y de cualquier intento de introducir una ruta arbitraria, además de 405 para POST. La página real contiene el Centro de mantenimiento y no contiene control de eliminación.

Esta validación no accedió a MySQL, a la base de datos de Traccar ni ejecutó limpieza. No requiere ni implica despliegue del código Phase 4 en los servicios persistentes.

## Regla visual oficial — continuidad con `/panel`

La interfaz de Traccar Manager adopta como referencia visual oficial el `/panel` original del servidor: fondo azul-negro, tarjetas oscuras con bordes discretos, acento cian, estados semánticos, radios moderados, jerarquía compacta y diseño responsive. La referencia se traduce a componentes propios del Manager; no se copia la lógica PHP ni el acceso directo de `/panel` a MySQL. Esta regla aplica a login, dashboard, mantenimiento y módulos futuros para conservar una identidad única.

## Incremento 5 — Preview operativo enriquecido

El Preview de logs incorpora métricas de inventario no destructivas: cantidad y tamaño total de logs históricos allowlisted, cantidad y bytes candidatos y rango temporal de los candidatos. El dashboard presenta estas métricas en tarjetas siguiendo el sistema visual derivado de `/panel`. El contrato conserva `active_log_protected=true` y `destructive_action_performed=false`; no se incorpora endpoint, permiso ni botón de eliminación.

La futura limpieza real queda deliberadamente fuera de este incremento. Antes de implementarla deberá definirse un protocolo independiente de preparación/confirmación que vincule una autorización efímera a un `preview_id` inmutable y vuelva a validar los archivos inmediatamente antes de cualquier mutación.

## Incremento 6 — núcleo PREPARED sin ejecución

Se incorpora el contrato puro `log_retention_prepare`: recibe exclusivamente un `preview_id` válido y la retención, vuelve a escanear la ruta fija `/opt/traccar/logs`, recalcula el hash del plan y falla con `PREVIEW_STALE` si cualquier candidato cambió. Si coincide, crea una preparación efímera de 5 minutos ligada al hash, conteo/bytes y nonce de un solo uso. El resultado declara `destructive_action_performed=false`.

Este incremento **no expone todavía endpoint HTTP/UDS, no concede `maintenance.logs.prepare` a ninguna cuenta y no contiene executor de borrado**. La siguiente puerta es integrar esta preparación con auditoría durable y el protocolo Worker; solo después podrá mostrarse en UI.

## Incremento 6 — Gate de Execute sin mutación
Se añadió el contrato puro `maintenance.logs.execute` en estado de diseño/gate, todavía no expuesto por HTTP/UDS ni habilitado en producción. Exige preparación válida, frase explícita `CONFIRMAR LIMPIEZA`, nonce exacto, TTL vigente y revalidación completa del Preview inmediatamente antes de ejecutar. El resultado actual fija `execution_enabled=false`, `authorization_consumed=false` y `destructive_action_performed=false`; no existe llamada a unlink/remove/rm. El próximo gate deberá resolver persistencia/consumo atómico de la preparación y autorización antes de incorporar cualquier mutación real.
