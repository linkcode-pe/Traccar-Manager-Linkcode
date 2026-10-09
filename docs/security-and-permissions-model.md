# Modelo de seguridad y permisos de Traccar Manager

**Estado:** diseño conceptual; no implementa ni habilita componentes. No sustituye ni modifica los mecanismos actuales de producción. Las referencias en `scripts/` no se ejecutan.

**Regla de independencia:** **Traccar debe seguir funcionando aunque Traccar Manager esté detenido.** El arranque básico y la recuperación propia de Traccar continúan bajo el sistema operativo y systemd, no bajo Manager.

## 1. Principios de seguridad

- Denegar por defecto; conceder únicamente los permisos imprescindibles para una operación concreta.
- Separar identidades, procesos, credenciales y bases de datos. Una vulnerabilidad en Web/API no debe conceder privilegios del Worker, del sistema operativo ni de Traccar.
- Validar el actor, el alcance, los parámetros, el estado previo y la autorización antes de crear un job ejecutable.
- No ofrecer shell general, `systemctl` general, SQL arbitrario, acceso irrestricto al filesystem ni lectura de secretos desde Web/API o el Worker normal.
- Registrar la diferencia entre solicitud, aprobación, intento y resultado confirmado. No registrar contraseñas, tokens, claves privadas ni datos sensibles innecesarios.
- Tratar un resultado incierto como `RECOVERY`: no repetir automáticamente operaciones cuyo efecto pueda haberse aplicado parcialmente.
- Los scripts de mantenimiento preservados en `scripts/` son referencias para análisis, no código operativo de Manager.

## 2. Mínimo privilegio

Cada componente tendrá una cuenta de servicio sin inicio interactivo, permisos de filesystem acotados y credenciales distintas. No se compartirán cuentas entre procesos con capacidades diferentes. Los binarios y el código serán de solo lectura para las cuentas de ejecución; solo directorios de estado expresamente definidos serán escribibles.

Los permisos de base de datos se concederán por esquema, tablas y operación, no globalmente. Los permisos privilegiados se aislarán en helpers pequeños, con interfaces allowlist, entradas validadas y resultados estructurados. Un permiso de lectura nunca implica permiso para modificar, borrar, reiniciar, instalar o migrar.

## 3. Usuarios y grupos propuestos

Nombres conceptuales sujetos a revisión durante una fase de implementación; no se crean en este documento:

| Identidad propuesta | Uso | Límite principal |
|---|---|---|
| `traccar-manager-web` | PHP Web/API | Sin root, shell ni acceso de escritura al código; solo API y tablas Manager necesarias. |
| `traccar-manager-scheduler` | Crear ocurrencias y jobs | Sin root, SQL arbitrario ni ejecución de handlers. |
| `traccar-manager-worker` | Procesar jobs ordinarios | Sin root; handlers explícitos y permisos de datos mínimos. |
| `traccar-manager-health` | Estado de Traccar y métricas | Lectura acotada; sin reinicios ni escritura en Traccar DB. |
| `traccar-manager-log-reader` | Lectura controlada de logs | Acceso de lectura únicamente a rutas autorizadas, con límites y redacción. |
| `traccar-manager-log-cleaner` | Futuro helper de retención de logs | Identidad separada, acceso limitado a los logs autorizados; no es el Worker general. |
| `traccar-manager-migrator` | Migration Runner por CLI | Sin root; privilegios DDL solo en Manager DB durante un apply autorizado. |
| Principal SQL de retención | Futuro borrado acotado de posiciones | Solo privilegios explícitos para tablas/operación aprobadas; nunca `GRANT`, DDL ni acceso global. |

Los nombres no indican que estas cuentas existan hoy.

## 4. Componentes que nunca deben ejecutarse como root

- PHP Web/API.
- Scheduler.
- Worker normal y handlers ordinarios.
- Lectores de salud, métricas y logs.
- Migration Runner; debe tener privilegios de base de datos limitados a Manager DB, no privilegios del sistema operativo.
- Código que construye vistas previas, valida solicitudes o procesa aprobaciones.

El instalador o una tarea administrativa puntual no debe convertirse en un servicio root permanente.

## 5. Componentes que podrían necesitar privilegios elevados

Solo una operación realmente privilegiada podría delegarse a un helper separado: borrar archivos de logs dentro de una allowlist o solicitar una acción concreta sobre `traccar.service`. El helper no debe ejecutar comandos recibidos del usuario ni heredar acceso root general para el Worker. La elevación debe ser por operación, limitada, auditable y revocable.

Las migrations requieren permisos DDL sobre **Manager DB** durante un apply aprobado, pero no root del sistema y nunca acceso DDL a Traccar DB.

## 6. Clasificación de operaciones

- **A — Solo lectura:** no altera el estado observado.
- **B — No destructiva:** crea información o artefactos reversibles, sin borrar el estado de origen.
- **C — Destructiva:** borra o reemplaza datos, archivos o estado.
- **D — Privilegiada:** requiere delegación controlada de permisos del sistema o de base de datos.
- **E — Autorización humana explícita:** no se ejecuta sin aprobación de una persona autorizada para el alcance concreto.

Una operación puede pertenecer a varias clases. La aprobación no convierte en segura una operación sin límites técnicos.

## 7. Matriz de operaciones

| Operación | Clase | Riesgo | Usuario recomendado / privilegios | ¿Automatizable? | Aprobación humana | Mecanismo y rollback |
|---|---|---|---|---|---|---|
| 1. Consultar estado de Traccar | A | Bajo | `traccar-manager-health`; sin root | Sí, lectura periódica | No por cada lectura; acceso autenticado | Lectura allowlist de propiedades. Sin rollback. |
| 2. Consultar CPU/RAM/disco | A | Bajo | `traccar-manager-health`; sin root | Sí, con límites de frecuencia | No por cada lectura | Métricas de solo lectura y rutas/dispositivos autorizados. Sin rollback. |
| 3. Consultar estado de servicios | A | Bajo | `traccar-manager-health`; sin root | Sí, solo servicios allowlist | No por cada lectura | Interfaz de lectura controlada; nunca `systemctl` arbitrario. Sin rollback. |
| 4. Leer logs controlados | A | Medio: privacidad y secretos | `traccar-manager-log-reader`; lectura de rutas acotadas | Sí, con límites | Autorización de acceso según rol; no aprobación por cada lectura ordinaria | Rutas, tamaño y período allowlist; paginación, redacción y auditoría. Sin rollback. |
| 5. Limpiar logs | C, D, E | Alto | Helper separado `traccar-manager-log-cleaner` | No borrar automáticamente; puede preparar una vista previa | Sí, para cada alcance y ejecución | Primero detectar y reportar; validar rutas, antigüedad y backup. Restaurar solo desde copia íntegra; borrar no siempre es reversible. |
| 6. Limpiar posiciones | C, D, E | Muy alto | Handler específico con principal SQL mínimo; nunca Web/API | No borrar automáticamente | Sí, con vista previa y alcance exacto | Consulta parametrizada y acotada; preview, respaldo verificable y autorización antes de DELETE. Rollback puede requerir restauración; no asumir que existe. |
| 7. Reiniciar Traccar | D, E | Alto: disponibilidad | Helper de control de servicio; no Worker root | Solo a partir de una acción aprobada; no por health check | Sí | Operación allowlist para `traccar.service`; registrar estado anterior y resultado. No revierte cambios de datos. |
| 8. Iniciar Traccar | D, E | Medio/alto | El mismo helper restringido | No por detección automática en esta fase | Sí | Acción explícita allowlist; comprobar resultado sin ejecutar comandos libres. Recuperación manual si falla. |
| 9. Detener Traccar | D, E | Alto: indisponibilidad | El mismo helper restringido | No | Sí | Acción explícita con advertencia de impacto y registro. Rollback operativo: iniciar de nuevo, si está autorizado. |
| 10. Actualizar Traccar | C, D, E | Muy alto: disponibilidad, datos y supply chain | Instalador aislado y acotado, no Web/API ni Worker | No sin política y autorización por release | Sí | Artefacto verificado, ventana, respaldo y plan de retorno a release íntegra anterior. |
| 11. Instalar plugins | C, D, E | Alto: código de terceros | Instalador controlado, sin privilegios persistentes | No | Sí, plugin y versión específicos | Validar origen, firma/hash y compatibilidad; conservar estado previo y procedimiento de retirada. |
| 12. Ejecutar migrations | D, E | Alto | Migration Runner Python por CLI, sin root | No desde HTTP, Scheduler ni jobs ordinarios | Sí, para el apply | Solo Manager DB; revisión previa, backup y ledger. Nunca migrations en Traccar DB. Rollback según migration; preferir forward-fix si no es reversible. |
| 13. Operaciones SQL | A para SELECT acotado; C/D/E para escrituras | Bajo en lectura; alto en escritura | Principal por función; Worker sin SQL arbitrario ni DDL | Lecturas allowlist sí; escrituras no sin autorización | Sí para cambios/borrados/DDL | Prepared statements y handlers nombrados; no aceptar texto SQL libre. DDL solo por Migrator sobre Manager DB aprobado. |
| 14. Crear backups | B; D solo si una ruta lo requiere | Medio/alto por confidencialidad y espacio | Usuario de backup limitado; sin root general | Sí, solo después de aprobar política, destino y retención | Aprobación inicial de política; revisión humana ante cambios o errores | Cifrar, verificar integridad y controlar acceso. Un backup no revierte por sí mismo una operación. |
| 15. Restaurar backups | C, D, E | Crítico | Restorer aislado y limitado al destino autorizado | No | Sí, explícita para backup, destino y alcance | Verificar hash/manifest, probar aislado y crear snapshot del estado actual. Restauración inversa solo si ese snapshot es válido. |

La hoja de ruta existente establece que la primera limpieza detecta y reporta, no elimina automáticamente. Este modelo mantiene esa restricción. Cualquier etapa posterior de borrado requiere una fase y autorización separadas.

## 8. Modelo Web / API / Job / Scheduler / Worker

1. **Web:** autentica y presenta información; no ejecuta comandos ni operaciones privilegiadas.
2. **API PHP:** valida identidad, rol, parámetros y alcance; crea solicitudes o jobs en Manager DB con tipo y payload tipado. No recibe SQL, shell ni rutas arbitrarias.
3. **Aprobación:** vincula a un actor humano, preview, operación, parámetros exactos, expiración y un identificador único. Una aprobación no se reutiliza para otro alcance.
4. **Scheduler:** solo crea ocurrencias y jobs persistentes; no ejecuta scripts ni habla con systemd. La identidad de slot es `(task_id, scheduled_at_utc)` con unicidad persistente.
5. **Worker Python:** procesa jobs ordinarios mediante handlers allowlist; no tiene root, DDL ni SQL arbitrario. Las tareas privilegiadas delegan únicamente al helper correspondiente, nunca a un shell general.
6. **Migration Runner Python CLI:** flujo administrativo aparte; migrations no son jobs, no se disparan por HTTP y solo operan en Manager DB durante un apply autorizado.

El Scheduler no equivale a un supervisor de Traccar. Si Manager está caído, Traccar conserva su ciclo de vida independiente.

## 9. Helpers privilegiados

Si una fase futura autoriza helpers, cada uno debe:

- Implementar una sola función y una allowlist cerrada de recursos; rechazar acciones, rutas, servicios y argumentos desconocidos.
- Ser propiedad de root y no modificable por Web/API ni Worker; recibir datos estructurados validados, no una cadena para shell.
- No ofrecer intérprete, SQL libre, acceso al filesystem completo ni opciones de escape.
- Aplicar límites de tiempo, tamaño, antigüedad, cantidad y concurrencia; usar bloqueo e idempotencia cuando corresponda.
- Registrar solicitante, job, preview, autorización, recurso, resultado y código de salida sin secretos.
- Devolver resultado estructurado y permitir distinguir `confirmado`, `fallido` e `incierto`.
- Ejecutarse separado del proceso Web/Worker y endurecerse con aislamiento de sistema operativo.

No usar `sudo` con comodines, shell genérico ni un servicio root que acepte comandos arbitrarios.

## 10. Límites de acceso a systemd

- No conceder al Worker, Web/API ni Scheduler acceso general a `systemctl`, D-Bus de administración o unidades arbitrarias.
- Las lecturas se limitan a propiedades allowlist de Traccar y servicios necesarios.
- Un futuro helper solo podrá actuar sobre `traccar.service` y acciones aprobadas explícitamente; no administrar timers, crear unidades ni alterar `Restart=`, watchdog o dependencias.
- Inicio, detención y reinicio requieren aprobación humana explícita. Health checks no deben provocar reinicios.
- El autostart básico y la política de reinicio de Traccar siguen siendo responsabilidad del sistema operativo, fuera del camino crítico de Manager.

## 11. Límites de filesystem

- Código y configuración de instalación: no escribibles por cuentas de ejecución.
- Datos de ejecución, logs de Manager y temporales: directorios separados, permisos mínimos y fuera del repositorio.
- Lectura de logs: rutas exactas, sin seguir enlaces simbólicos fuera del árbol autorizado; límites de bytes/líneas/tiempo y redacción de identificadores sensibles.
- Limpieza: helper limitado a un directorio fijo, nombres/patrones validados y cutoff aprobado; no aceptar ruta de usuario ni comodines libres.
- No exponer `/root`, `/etc` protegido, dispositivos, sockets generales ni el filesystem completo a Manager.
- Backups, dumps, `.env`, claves y datos sensibles no se versionan ni se publican.

## 12. Límites de MySQL

- Mantener Manager DB separada de Traccar DB y usar credenciales distintas.
- Web/API y Worker ordinario solo reciben DML estrictamente necesario en tablas Manager; no DDL.
- Health de Traccar utiliza SELECT limitado a vistas/tablas necesarias y no escribe en Traccar DB.
- El borrado de posiciones, si se autoriza en una fase futura, usa un principal dedicado con permisos mínimos sobre el alcance aprobado; consultas preparadas, límites y preview. Sin `DROP`, `ALTER`, `GRANT`, privilegios globales ni acceso a otras bases.
- El Migration Runner obtiene permisos DDL solo sobre Manager DB durante el apply autorizado; no accede a Traccar DB.
- Ningún endpoint recibe SQL arbitrario ni construye SQL concatenando parámetros de usuario.

## 13. Protección de credenciales y secretos

- Mantener secretos fuera del repositorio, DocumentRoot, logs, errores, previews y respuestas API.
- Usar almacenamiento protegido o archivos externos con permisos mínimos; nunca guardar credenciales dentro de scripts de referencia.
- Credenciales distintas por servicio y entorno; limitar, rotar y revocar tras exposición.
- No leer secretos para diagnosticar tareas que no los necesitan. No imprimir valores secretos al validar configuración.
- Ocultar secretos en excepciones, argumentos de procesos, volcados, telemetría y auditoría.

## 14. Auditoría y registro

Registrar en un ledger protegido y preferentemente append-only: actor autenticado, rol, solicitud, preview/hash, autorización y motivo, job/slot, handler/version, recurso, tiempos, intentos y resultado confirmado. Registrar también rechazos y cambios de estado. No guardar secretos ni contenido sensible innecesario.

El estado incierto pasa a `RECOVERY`, sin reintento automático. Una alerta `CRITICAL` bloquea nuevas ejecuciones; atenderla no desbloquea por sí solo. El desbloqueo administrativo, si se implementa, requiere permiso y motivo, y solo habilita una nueva preview; cualquier ejecución posterior es un job nuevo y necesita una autorización nueva cuando aplique.

## 15. Rollback y recuperación

- Antes de actualizar, instalar plugins, aplicar migrations o borrar datos: verificar alcance, hashes, backup recuperable y procedimiento de retorno.
- Probar restauraciones en entorno aislado antes de confiar en un backup.
- No afirmar que un `DELETE` tiene rollback una vez confirmado; restaurar puede requerir una copia consistente y afectar datos posteriores.
- Para migrations no reversibles, preferir una migration correctiva hacia adelante, bajo autorización, en vez de alterar el historial aplicado.
- Ante timeout o resultado incierto: consultar estado de forma no destructiva y pasar a `RECOVERY`; no repetir una operación potencialmente aplicada.
- El rollback nunca debe iniciar, detener o modificar producción sin autorización específica.

## 16. Reglas para futuras automatizaciones

- Empezar por detectar y reportar. La automatización inicial de limpieza no borra.
- Separar preview, clasificación, confirmación, respaldo, ejecución y verificación; cada fase deja evidencia.
- Las tareas seguras pueden tener catch-up solo dentro de una ventana definida y como máximo una vez por slot. Las destructivas no hacen catch-up automático.
- Reintentar solo errores recuperables según el handler y un límite explícito; resultado incierto va a `RECOVERY`, nunca a reintento automático.
- No permitir que una alerta crítica se desbloquee automáticamente.
- Una programación no es aprobación: cada operación destructiva o privilegiada requiere autorización humana explícita para su alcance.
- Los timers actuales de producción no se reemplazan ni modifican por esta propuesta.

## 17. Separación entre Traccar y Manager

Traccar y Manager son productos y dominios operativos separados. Manager puede supervisar estado y ofrecer administración controlada futura; no debe poseer los archivos, plugins, logs, datos ni migrations de Traccar como si fueran parte de su repositorio. La caída, actualización o mantenimiento de Manager no debe detener Traccar.

## 18. Independencia operativa

La unidad de Traccar y el sistema operativo conservan el autostart básico y su comportamiento independiente. Manager es una capa opcional de supervisión/administración; nunca un requisito para iniciar, servir tráfico o recuperarse del fallo básico de Traccar.

## 19. Contradicciones y aclaraciones documentales

- `architecture-overview.md` y `development-roadmap.md` son conceptuales y exigen interfaces controladas, detección previa y aprobación para acciones destructivas. Este documento lo concreta; no declara que exista integración con Traccar DB ni que el modelo esté implementado.
- `project-structure.md` indica que `scripts/` no contiene scripts funcionales. Actualmente existen archivos de referencia no ejecutables; esa frase no debe interpretarse como que la carpeta está vacía ni como permiso para ejecutarlos. No se modifica aquí la documentación existente.
- El diseño separa Manager DB de Traccar DB y reserva las migrations para CLI Python sobre Manager DB. Si otra documentación futura propone DDL sobre Traccar DB o migrations vía HTTP/jobs, debe resolverse la contradicción antes de implementar.

## 20. Estado de implementación

Este archivo es diseño. No crea usuarios, grupos, tablas, API, Worker, Scheduler, helpers, unidades, timers, permisos, conexiones a bases de datos ni automatizaciones. Las decisiones de implementación, pruebas y operación productiva requieren fases y autorizaciones separadas.
