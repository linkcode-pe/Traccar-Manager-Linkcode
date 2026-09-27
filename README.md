# Traccar Manager

**Estado:** estructura inicial del proyecto; no implementa todavía funcionalidades web, administración, mantenimiento, integraciones ni instalador.

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
