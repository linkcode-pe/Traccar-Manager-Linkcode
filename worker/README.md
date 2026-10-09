# Worker no-root — estado de preparación

Esta carpeta contiene scaffolding aislado. No hay proceso Worker, loop de cola, Scheduler, cuenta Unix dedicada, servicio ni permisos adicionales configurados. No se creó ningún usuario/grupo y no se cambiaron permisos de producción. El Worker no se inicia ni queda integrado a la aplicación.

## Identidad propuesta

- Usuario: `traccar-manager-worker`.
- Grupo: `traccar-manager-worker`.
- Para lectura de estado se puede separar más adelante una identidad `traccar-manager-health`; no existe hoy.
- Ambos son nombres propuestos solamente; no crear sin una fase autorizada de cuentas/permisos.

## Lectura y escritura mínimas previstas

- Leer código y schemas allowlist bajo `/opt/traccar-manager/worker/`; el árbol debe ser propiedad administrativa y no escribible por el Worker.
- Recibir jobs y actualizar únicamente sus estados mediante un repository/credencial acotado a tablas Manager DB cuando ese backend se autorice. No aceptar SQL ni modificar esquema.
- No leer archivos de credenciales, `.env`, claves, trust stores, configuración protegida, Traccar DB ni los scripts de referencia de limpieza. La entrega futura de credenciales del Manager DB requiere canal seguro y permisos mínimos; si no existe, el Worker debe fallar cerrado.
- No escribir en el repositorio, `/opt/traccar/`, Traccar Web, Apache, systemd ni timers. No hay directorio runtime creado. Si una fase posterior necesita estado temporal, proponer un directorio externo como `/var/lib/traccar-manager/worker/`, propiedad de la identidad dedicada y limitado a sus archivos de estado.
- La auditoría se entrega por una interfaz `AuditSink` obligatoria; no se implementó backend, archivo de log ni tabla. Sin sink operativo, no se debe despachar trabajo.

## Operaciones y límites

- La única operación en el registry es `traccar.status`; payload vacío, role `traccar.status.read`, unidad fija `traccar.service`, propiedades de estado allowlist.
- El adapter usa solo una consulta fija de lectura `systemctl show` con `shell=False`; no recibe nombre de unidad/comando del job. No se concedió acceso sudo, control de systemd, escritura de unidades ni timers. El helper rechaza UID 0. No se probó la consulta contra systemd.
- Dispatcher valida el Job, el rol y un verificador de autorización inyectado, exige auditoría antes/después y despacha solo por registry estático. No hay autenticador, verifier, cola ni worker loop productivos.
- El Worker no puede ejecutar shell, comandos de usuario, SQL arbitrario, DDL, scripts de limpieza, inicio/detención/reinicio, instalación/actualización, migrations ni restauraciones.
- Helpers privilegiados futuros son procesos separados con interfaz allowlist; nunca root general dentro del Worker. La limpieza de logs o posiciones no está registrada como operación.

El código es fuente con modo no ejecutable, no se invocó `traccar.status` y esta estructura no constituye integración productiva.
