# Prueba visual aislada de Dispositivos

Ejecutar desde la raíz del proyecto: `scripts/run-visual-fixture.sh`.

La prueba usa Playwright instalado en `.visual-test/node_modules` (directorio local excluido de Git) y solicita el HTML y los iconos públicos del Manager. Intercepta todas las rutas `/api/` y devuelve exclusivamente datos ficticios. **No inicia sesión real, no lee dispositivos GPS y no ejecuta operaciones de mantenimiento.**

Comprueba la vista autenticada simulada, la combinación de búsqueda y filtros, la privacidad de identificadores y la ausencia de errores JavaScript. Genera tres capturas locales, con sufijos `-mobile.png`, `-tablet.png` y `-desktop.png`, partiendo de `/tmp/manager-devices-fixture.png` o de la ruta indicada por `SCREENSHOT_PATH`. También comprueba que no haya desplazamiento horizontal inesperado en los tres tamaños y que la ficha de diagnóstico se abra correctamente, pueda cerrarse con Escape y devuelva el foco al dispositivo original.

Para instalar la dependencia en un entorno de pruebas nuevo, dentro de `.visual-test/` ejecutar `npm install playwright` y `npx playwright install chromium`. No se requieren estas dependencias para ejecutar la aplicación en producción.
