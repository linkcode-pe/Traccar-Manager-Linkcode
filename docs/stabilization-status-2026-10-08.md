# Estabilización del Manager — 2026-10-08

## Evidencia

- Servicios `traccar.service` y `traccar-manager.service`: activos al comprobarlos.
- URL pública `/manager/`: HTTP 200 al comprobarla.
- Suite Python ejecutada sobre copia temporal sin permisos privilegiados: **338 passed, 9 skipped, 78 subtests passed**.
- El procedimiento reproducible es `scripts/run-isolated-tests.sh`.
- Las lecturas de incidentes y auditoría se redirigen a fixtures vacíos **solo en la copia de pruebas**; no se alteran rutas de producción.

## Pendientes

- Revisar y consolidar archivos Git no rastreados; nunca incluir credenciales, secretos, logs, respaldos o datos de runtime.
- Documentar pruebas omitidas y cobertura de integración real.
- Verificar navegador móvil y autenticación sin exponer datos de dispositivos.
- Completar los iconos realistas del catálogo (hay categorías con iconos provisionales).
- Mantener bloqueada la eliminación de mantenimiento hasta disponer de respaldo y verificación autorizados.
- No confundir tests aislados con validación de producción.

## Integridad de iconos

- `python3 scripts/check-vehicle-icons.py --url https://homecargps.com/manager/` verificó 30/30 archivos WebP, estructura RIFF, HTTP 200, tipo MIME y bytes servidos idénticos al archivo local.
- La integridad de los archivos no implica aprobación estética: algunas categorías conservan iconos provisionales.
- No se utilizaron credenciales ni datos GPS para esta comprobación.
