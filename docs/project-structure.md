# Estructura del proyecto

## Ubicación

La raíz prevista del proyecto es `/opt/traccar-manager/`. Esta documentación describe la estructura inicial; no implica que otros componentes estén implementados.

## Separación respecto de otros proyectos

- `/opt/traccar/` es la instalación real de Traccar y debe permanecer separada. No copiar aquí sus archivos, plugins, logs, datos ni migrations.
- `/opt/modificaciones/traccar-web-6.7.2/` es un proyecto Traccar Web independiente, con repositorios Git propios. No reutilizarlo como raíz ni modificarlo desde este proyecto.
- Traccar Manager tendrá su propio repositorio. Configuración, datos de ejecución, logs y backups deberán permanecer fuera de él.

## Propósito de carpetas

- `runner/`: código principal de administración y lógica del proyecto.
- `tests/`: pruebas automatizadas.
- `docs/`: arquitectura, instalación, operación, seguridad y manuales.
- `migrations/`: únicamente migrations propias de Traccar Manager que se diseñen posteriormente; nunca copiar migrations de Traccar.
- `release/`: artefactos de futuras releases.
- `scripts/`: scripts auxiliares propios cuando existan; actualmente no contiene scripts funcionales.
- `deployment/`: materiales de despliegue futuro; actualmente sin configuración de despliegue.
- `installer/`: componentes de un futuro instalador; actualmente no es un instalador funcional.

## Fuera del repositorio

No versionar `.env`, credenciales, claves privadas, certificados privados, tokens, trust stores privados, dumps, bases de datos, logs sensibles, datos de ejecución, backups, dependencias instaladas ni archivos temporales. El `.gitignore` inicial cubre las categorías principales sin ignorar migrations `.sql` legítimas ni el código o la documentación.
