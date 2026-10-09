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

## Escritura condicionada y validación de extremo a extremo

El ejecutor ahora admite `--apply` únicamente después de obtener el código de salida real 0 de `run-isolated-tests.sh`. La escritura se realiza con identidad no root y permisos sobre el SQLite de progreso; el registrador rechaza degradar una tarea ya verificada. Sin `--apply` continúa el modo vista previa.

Validación E2E aislada (2026-10-09): repositorio copiado bajo cuenta `nobody`, base SQLite temporal, batería completa sin fallos, evento aplicado `test-run-a04474ba09d1c39d9541d315`, estado PROG-006 `in_testing`, documentación `in_review`, 1 evento persistido. Producción no recibió el evento de esta prueba. Pendiente habilitar ejecutor de confianza y automatizar el disparador, sin exponer el permiso de escritura a la interfaz pública.

## Primer evento productivo controlado — 2026-10-09

Se instaló el ejecutor en `/opt/traccar-manager/scripts/` y se invocó manualmente como root `python3 scripts/run-tests-with-progress.py --task PROG-006 --apply`. La batería aislada finalizó con código 0, el registrador escribió como `traccar-manager-web`, evento `test-run-ac86f28e2f62e950da2fdab9`, informe `docs/test-runs/PROG-006-a83ef92751ad-8f0cd00aa481.md`. Verificación posterior: PROG-006 `in_testing`, documentación `in_review`, último evento visible en snapshot, 0/77 verificadas y HTTP 200. Se respaldó SQLite antes de ejecutar. El HEAD del checkout productivo (`a83ef92751ad`) no incluye todavía los cambios sin confirmar de su árbol de trabajo; no interpretar el SHA como identificación íntegra del código probado. No se configuró ejecución periódica.

Para evitar escrituras arbitrarias, `--apply` requiere root y restringe actualmente la tarea a PROG-006; el registro se delega a la cuenta de servicio sin privilegios de root. La aceptación funcional sigue pendiente.

## Protección de evidencias y control de versión

Antes de aplicar, el registrador combina evidencias nuevas con las anteriores sin duplicados y rechaza la operación si superan 20 referencias. No elimina evidencias previas para hacer sitio. El ejecutor con `--apply` rechaza un checkout con cambios en archivos rastreados: el SHA del commit no identifica entonces íntegramente el código ejecutado. La protección no sustituye un manifiesto de artefactos para archivos no rastreados. No se habilita un temporizador productivo mientras el checkout permanezca modificado.

Pruebas de laboratorio: segundo evento con evidencia adicional aplicado a SQLite aislado, total 3 evidencias conservadas; guardia de checkout modificado devuelve código 6 sin ejecutar la batería ni escribir en progreso.

## Manifiesto verificable de fuente (2026-10-09)

`python3 scripts/source-manifest.py --root /opt/traccar-manager --output /ruta/manifest.json` genera un inventario determinista con SHA256 por archivo y SHA256 global. Incluye archivos fuente no rastreados en Git dentro de los directorios de aplicación, excluye cachés, dependencias y artefactos generados. El ejecutor compara la huella antes/después de pruebas y usa la huella global para nombrar informe y evento; conserva el commit Git como metadato secundario. No incluye secretos, datos SQLite ni archivos fuera de los directorios declarados. Este control detecta cambios en los archivos cubiertos, pero no sustituye firma criptográfica ni protección frente a un atacante con acceso root.

Validación de laboratorio: batería aislada terminó con código 0, evento en vista previa vinculado al manifiesto SHA256 `c71f6ae162bd295ad1226fac983e3204877717eec6f6c20d7044334cf64c0be3`. Manifiesto de fuente productiva medido por separado: 140 archivos; SHA256 `daadf275ed0118fed4e58f4acbdd9859d89ebd03741742afb91c7ee973e3649d` (fotografía puntual, no verificación continua).
