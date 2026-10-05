# Estructura del proyecto

## Raíz de despliegue

La instalación actual usa `/opt/traccar-manager/`. El repositorio define el producto, pero datos de ejecución, secretos, logs, backups y estado mutable deben permanecer fuera de Git.

## Separación respecto de Traccar

- `/opt/traccar/` corresponde a la instalación real de Traccar y permanece separada.
- Traccar Manager no copia ni absorbe el código, logs, datos o migrations de Traccar dentro de su repositorio.
- Otros proyectos Traccar Web existentes en el servidor no forman parte de este repositorio.

## Componentes actuales

- `api/`: contratos, proveedores y adaptadores de API del Manager.
- `manager/`: aplicación web Python, sesiones/autenticación, RBAC, puente hacia Worker y lógica del dashboard.
- `worker/`: Dispatcher, servidor UDS, operaciones permitidas y auditoría.
- `web/`: interfaz web y adaptadores cliente.
- `deploy/`: unidades/configuración de despliegue del Worker y comunicación local.
- `tests/`: pruebas automatizadas y fixtures.
- `docs/`: arquitectura, seguridad, auditoría, integración, operación y hoja de ruta viva.
- `scripts/`: scripts auxiliares y scripts históricos/operativos que pueden convertirse en operaciones controladas del Manager.
- `migrations/`: migrations propias de Traccar Manager; nunca migrations copiadas de Traccar.
- `installer/`: base para el instalador guiado reutilizable.
- `deployment/`: documentación/materiales de despliegue.
- `release/`: artefactos y definición futura de releases.
- `runner/`: componentes heredados/auxiliares del proyecto; su función debe mantenerse explícita al evolucionar.

## Regla para scripts

La existencia de un script en `scripts/` no implica que el navegador pueda ejecutarlo directamente. Para convertirse en una función del dashboard debe existir una operación Worker explícita, validación de parámetros, permiso RBAC, auditoría y pruebas. Las acciones destructivas requieren además previsualización/confirmación y verificación.

## Portabilidad

El producto debe poder instalarse posteriormente en servidores externos. No introducir dependencias rígidas de `homecargps.com`, IDs locales, credenciales, rutas privadas o estado mutable sin una capa de detección/configuración del instalador.

## Fuera del repositorio

No versionar `.env`, credenciales, claves privadas, certificados privados, tokens, trust stores privados, dumps, bases de datos, logs sensibles, datos de ejecución, backups, dependencias instaladas ni archivos temporales.