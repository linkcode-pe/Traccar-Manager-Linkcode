# Traccar Manager

**Estado (2026-10-08):** Manager web desplegado y operativo en `/manager/`, con autenticación, panel administrativo, inventario de dispositivos de solo lectura, diagnóstico y componentes de auditoría. El proyecto sigue en desarrollo: no se considera terminada la integración integral con Traccar, el instalador ni la distribución. La eliminación de mantenimiento en producción continúa bloqueada.

## Validación técnica actual

- Servicios comprobados activos: `traccar.service` y `traccar-manager.service`.
- Pruebas aisladas reproducibles: `scripts/run-isolated-tests.sh --disable-warnings` (338 aprobadas, 9 omitidas y 78 subpruebas aprobadas en la última ejecución).
- Informe de estabilización: [docs/stabilization-status-2026-10-08.md](docs/stabilization-status-2026-10-08.md).
- Integridad de los iconos publicados: `python3 scripts/check-vehicle-icons.py --url https://homecargps.com/manager/` (30/30 correctos).
- La validación de laboratorio no sustituye las pruebas autenticadas y visuales en producción.
- No subir secretos, respaldos ni estado de ejecución a Git. Los archivos nuevos requieren revisión antes de su incorporación.

## Propósito

Sistema web independiente para administrar y supervisar un servidor Traccar.

## Principio arquitectónico

Traccar Manager debe funcionar como una aplicación separada de Traccar. En fases futuras podrá interactuar con tablas y servicios de Traccar mediante interfaces claramente definidas, controladas y documentadas. Esta relación no implica que exista hoy una conexión o integración activa.

## Objetivos iniciales

- Administración del servidor Traccar y diagnóstico.
- Mantenimiento y gestión de archivos.
- Identificación y reporte de archivos posiblemente innecesarios.
- Herramientas futuras de limpieza controlada y otras funciones de administración.
- Documentación técnica y operación segura.
- Una instalación sencilla en servidores externos que utilicen Traccar.

## Separación de componentes

Mantener separados Traccar, Traccar Manager, la configuración, los datos, los logs y los backups. La configuración sensible y los datos de ejecución no pertenecen al repositorio Git.

## Seguridad y acciones destructivas

Traccar Manager nunca debe modificar archivos de Traccar de forma destructiva sin una acción explícita, validación previa y mecanismo de recuperación. La detección y el reporte preceden a cualquier acción. La limpieza de archivos es de alto riesgo: su ciclo futuro deberá distinguir **DETECTAR, PREVISUALIZAR, CLASIFICAR, CONFIRMAR, RESPALDAR, ELIMINAR y VERIFICAR**. La primera versión de esa función será solo de detección y reporte; nunca habrá borrado automático de “basura”.

Nunca almacenar en este repositorio credenciales, claves privadas, tokens, dumps, logs sensibles ni archivos de configuración secretos.

## Responsable y herramientas

- **Propietario y responsable:** Jim Ramos.
- **Asistencia de IA:** apoyo de arquitectura, análisis y desarrollo asistido.
- **Zapia:** ejecución técnica autorizada en el servidor.

## Carpetas

Consulta [docs/project-structure.md](docs/project-structure.md) para el propósito de cada carpeta y [docs/development-roadmap.md](docs/development-roadmap.md) para las etapas futuras.

La licencia está pendiente de decisión del propietario; el archivo `LICENSE` es solo un marcador documental y no concede una licencia.
