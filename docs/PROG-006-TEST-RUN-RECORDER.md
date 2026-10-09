# PROG-006 — Registrador de pruebas para progreso

`python3 scripts/progress-record-test-run.py --task AUD-003 --report docs/AUD-001-AUD-003-VALIDACION-2026-10-09.md --revision 5d69e51 --exit-code 0` muestra un evento sin escribir. Solo `--apply` lo registra; debe ejecutarse como cuenta de servicio no root con acceso controlado a SQLite.

- El informe debe existir dentro de `docs/`, ser legible y menor de 200 KB.
- Se rechazan resultados distintos de código cero y revisiones que no parezcan SHA.
- El identificador deriva de tarea, revisión y SHA256 del informe para evitar eventos duplicados.
- El estado máximo emitido es `in_testing` y documentación `in_review`; nunca `verified`.
- Esta utilidad no demuestra que el código de salida suministrado sea auténtico. Para integración CI confiable, el ejecutor deberá invocarla únicamente tras la finalización comprobada de la batería y con un informe generado por ese mismo proceso. No conceder permisos de escritura de SQLite a usuarios generales.
- El registro no reemplaza validación de aceptación ni auditoría de seguridad.

Estado: implementación en laboratorio, pendiente de integración controlada y prueba de extremo a extremo del ejecutor CI.

## Ejecución conectada con el resultado real

`python3 scripts/run-tests-with-progress.py --task PROG-006` ejecuta la batería aislada, captura el código real de salida, genera un informe versionable en `docs/test-runs/` con SHA256 y llama al registrador en modo vista previa **solo si la batería pasa**. Un fallo o timeout no genera evento de progreso. El script no tiene modo de escritura: integrar la aplicación automática requiere un ejecutor de confianza, permisos mínimos y pruebas adicionales de seguridad.

Validación de laboratorio 2026-10-09: ejecución terminada con código 0, informe `docs/test-runs/PROG-006-60f01304724c-594e6ae9a7e8.md`, evento `test-run-e58a2eb8459cd01e49891f24` generado en vista previa.
