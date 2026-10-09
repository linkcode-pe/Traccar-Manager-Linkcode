# Revisión integral de Traccar Manager — progreso (2026-10-08)

## Alcance y estado

Revisión progresiva; **no completada**. Entorno de producción: `https://homecargps.com/manager/`. Código principal de interfaz: `manager/web_app.py`. Las pruebas de navegador utilizan una sesión y respuestas API **simuladas**; no son una prueba autenticada de todas las operaciones reales.

## Inventario de navegación verificado en código

| Módulo | Estado de revisión | Próxima revisión |
| --- | --- | --- |
| Dashboard (`summary`) | Revisado parcialmente; flota, prioridades, búsqueda, filtros, expansión y CSV probados | Integridad de KPI, alertas y gráficos ante respuestas parciales |
| Servidor (`server`) | Revisión estructural inicial; encabezados de diagnóstico corregidos | Servicios, diagnósticos, capacidad, tendencias e historial |
| Base de datos (`database`) | Identificado, pendiente de revisión funcional completa | Estados de error, privacidad y lectura segura |
| Dispositivos (`devices`) | Listado, filtros, diagnósticos y estados probados con fixture | Pruebas de inventario real autenticado y accesibilidad completa |
| Mantenimiento (`maintenance`) | Identificado, pendiente de revisión funcional completa | Contratos de previsualización y protección contra acciones destructivas |
| Centro de alertas (`alerts`) | Identificado, pendiente de revisión funcional completa | Estados, filtros y alertas con datos reales autorizados |
| Auditoría (`audit`) | Identificado, pendiente de revisión funcional completa | Eventos sanitizados, navegación e historial |
| Cuenta/perfil | Identificado como bloque independiente | Sesiones, accesibilidad, carga de avatar y privacidad |

## Hallazgos y correcciones aplicadas

1. El panel de exportación de prioridades no advertía junto al botón que los datos podían tener más de 15 minutos. Se añadió un aviso accesible que aparece al caducar el inventario y desaparece tras una actualización correcta. El CSV ya contiene el estado de vigencia.
2. Dos bloques de diagnóstico del módulo Servidor usaban `id="diagnostic-title"`, rompiendo la unicidad de identificadores y asociando incorrectamente un encabezado. El bloque de diagnóstico preventivo ahora usa `preventive-diagnostics-title`.

## Evidencia de validación

- Fixture Playwright en móvil, tableta y escritorio: aprobado; incluye advertencia de vigencia, exportación CSV y encabezados de diagnóstico.
- Pruebas aisladas: 338 aprobadas, 9 omitidas, 78 subpruebas aprobadas.
- Iconos WebP: 30 verificados, 0 errores.
- Servicios `traccar` y `traccar-manager`: activos tras el despliegue; HTTPS público: HTTP 200.

## Límites y prioridades siguientes

1. Auditoría de seguridad y funcionamiento de las rutas administrativas (sin ejecutar acciones destructivas).
2. Cobertura funcional de Servidor, Base de datos, Mantenimiento, Alertas y Auditoría con fixtures de fallos y respuestas parciales.
3. Revisión de accesibilidad global: nombres accesibles, navegación por teclado, estados de carga y encabezados.
4. Comprobación de rendimiento y robustez con cargas realistas y sin datos sensibles.
5. Validación autenticada en producción de las operaciones de solo lectura, si se dispone de una sesión de pruebas autorizada.

No se considera terminada la integración integral con Traccar, el instalador ni la distribución. La eliminación de datos de mantenimiento en producción permanece bloqueada.

## Segunda revisión: controles de acceso y accesibilidad (2026-10-08)

- Se inventariaron las rutas HTTP GET/POST expuestas por `ManagerRequestHandler`, incluidos los recursos de autenticación, cuenta, dashboard, inventario, servidor, auditoría, salud y mantenimiento. No se ejecutaron acciones administrativas de escritura.
- Ocho rutas protegidas consultadas **sin sesión** por HTTPS (`auth/me`, `dashboard/snapshot`, `server/status`, `devices/inventory`, `audit/recent`, `maintenance/logs/preview`, `account/profile`, `health/incidents`) respondieron **401**; esto no equivale a una auditoría completa de autorización por roles.
- La respuesta pública declara `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` y política CSP restrictiva. La revisión no demuestra ausencia de vulnerabilidades.
- Se añadieron aserciones de navegador para detectar identificadores HTML duplicados y referencias rotas de `aria-labelledby`, `aria-describedby` y etiquetas `for`, en los tres tamaños de pantalla.
- Pendiente: comprobar exhaustivamente autenticación con sesión autorizada, autorización por operación, manejo de fallos parciales y pruebas funcionales de los demás módulos.

## Tercera revisión: alertas ante evidencias parciales (2026-10-08)

- En el módulo Centro de alertas se encontró una excepción JavaScript posible: `renderAlerts()` comprobaba `p.journal.status` y `p.binlogs.status` sin verificar que ambos objetos existieran. Un snapshot de protección parcial podía interrumpir el renderizado de alertas.
- Se modificó el tratamiento para emitir avisos críticos de **evidencia ausente o configuración desviada** cuando falta el bloque journal/binlogs, en vez de lanzar una excepción. La comprobación de sobreuso de journal solo opera con números finitos y un límite positivo.
- Este cambio no relaja los controles de protección ni habilita mantenimiento destructivo. Se despliega solo la interfaz de Manager; Traccar permanece intacto.
- Pendiente: fixture específico de respuesta parcial del servidor y pruebas autenticadas de lectura en producción.

## Cuarta revisión: regresión específica de alertas (2026-10-08)

- Se añadió `tests/visual/alerts-partial-fixture.mjs`, que ejecuta el cuerpo **real** de `renderAlerts` extraído del código de Manager dentro de un contexto JavaScript aislado, sin llamar a APIs productivas.
- Casos aprobados: protección journal/binlogs ausente, evidencia saludable, snapshot ausente y estado de servicio nulo. Verifica textos y contadores de alertas.
- Se corrigió otro acceso no protegido a `s.active_state`/`s.sub_state` cuando el estado de un servicio es `null`; ahora se muestra `sin evidencia` y una alerta crítica.
- El runner `scripts/run-visual-fixture.sh` incluye la nueva regresión. La ejecución completa de pruebas visuales y aisladas pasó. No equivale a una prueba autenticada en producción.

## Quinta revisión: invalidación segura de preparación de mantenimiento (2026-10-08)

- En `previewLogs`, un nuevo intento de análisis no invalidaba `lastPreview`/`lastPreparation` hasta después de recibir una respuesta válida. Si fallaba la validación o la consulta, podían persistir referencias y controles de una preparación anterior.
- Ahora cada nueva solicitud de análisis invalida inmediatamente los tokens de vista previa/preparación y oculta los controles de preparación/ejecución y evidencias anteriores. No se llama a `prepare` ni `execute` durante las pruebas.
- Nuevo fixture aislado `tests/visual/maintenance-preview-fixture.mjs`: retención inválida y fallo de consulta invalidan la autorización anterior; incorporado al runner visual.
- Se conservaron el gate productivo y los controles del backend. Pendiente: prueba autenticada de solo lectura de `maintenance/logs/preview` y revisión integral de la sección.

## Sexta revisión: Centro de capacidad con evidencia incompleta (2026-10-08)

- Se detectó que `renderCapacityCenter` podía dividir entre un total de disco igual a cero o ausente, generando porcentajes inválidos y dejando componentes visuales previos visibles.
- Ahora, ante capacidad no verificable, el centro elimina la distribución anterior y muestra `Capacidad no verificable · sin total de disco válido` y `No disponible`, sin fabricar métricas.
- Nuevo `tests/visual/capacity-partial-fixture.mjs` comprueba capacidad cero, total válido y total ausente. Integrado en `scripts/run-visual-fixture.sh`.
- Las pruebas son simuladas, ejecutan el código de renderizado real en aislamiento y no requieren datos de producción. Pendiente revisar el resto del módulo Servidor/Base de datos y comprobar sesión autenticada.

## Séptima revisión: Base de datos sin métricas confirmadas (2026-10-08)

- El bloque de error de `loadServerStatus` no invalidaba los indicadores del módulo Base de datos después de un fallo de consulta. Podía conservar datos anteriores y aparentar una lectura reciente.
- Ahora el estado de error muestra `Metadatos no disponibles · sin lectura confirmada`, reinicia totales, conteos, KPI y porcentajes de índices/posiciones.
- Se incorporó `tests/visual/database-error-fixture.mjs` al runner visual. Es una aserción de regresión **estática sobre el código del manejador de error**, no una simulación dinámica de una consulta de Base de datos ni una prueba autenticada. Pruebas visuales y aisladas completas aprobadas.
- Pendiente: prueba dinámica de respuesta fallida y revisión integral de la sección Base de datos.

## Octava revisión: Auditoría con eventos parciales (2026-10-08)

- `loadAuditHistory` suponía que todos los elementos de `events` eran objetos. Un `null` provocaba excepción y hacía perder la lista completa, incluso cuando había eventos válidos.
- Ahora se filtran entradas nulas/no objeto y se muestran `Evento sin tipo` / `No verificable` cuando falta información de una entrada válida. La vista conserva `textContent`, sin interpolación HTML de eventos.
- Nuevo fixture dinámico aislado `tests/visual/audit-partial-fixture.mjs`: comprueba eventos heterogéneos y solicitud fallida. Integrado al runner visual. No usa una sesión productiva.
- Pendiente: revisar permisos y contratos de eventos con sesión de prueba autorizada; ampliar pruebas de Cuenta/perfil.

## Novena revisión: Cuenta y cambio de contraseña sin conexión (2026-10-08)

- El evento `password-save` no capturaba excepciones de red. Una desconexión podía dejar el mensaje `Actualizando…` y una promesa rechazada sin manejar.
- Se añadió manejo explícito de fallos de conexión con un mensaje recuperable, conservando las validaciones de coincidencia y longitud y la lógica del backend.
- Nuevo fixture aislado `tests/visual/password-network-fixture.mjs` prueba rechazo de red y contraseñas diferentes sin hacer solicitudes a producción; incluido en el runner visual. No se modificaron credenciales reales.
- Pendiente: revisión del flujo de avatar, permisos de Cuenta y prueba autenticada no destructiva.

## Décima revisión: carga de avatar de Cuenta (2026-10-08)

- La carga de avatar no capturaba excepciones de FileReader o red; podía dejar una vista previa local sin aclarar que no se había guardado la foto.
- Ahora captura fallos, muestra un mensaje recuperable y vuelve a consultar el perfil; conserva el límite local de 2 MiB y la validación del backend. No se envió ningún avatar real.
- Nuevo fixture dinámico aislado `tests/visual/avatar-network-fixture.mjs`: simula desconexión y rechazo de archivo de más de 2 MiB; incluido en el runner visual. Pruebas generales y visuales completas aprobadas.
- Pendiente: pruebas autenticadas de carga válida en entorno de pruebas, permisos y accesibilidad completa de Cuenta.

## Undécima revisión: validación y errores de perfil (2026-10-08)

- El guardado de perfil no comprobaba el formato del correo en cliente y mostraba el mismo mensaje para errores de validación, desconexión y fallo 5xx.
- Ahora valida nombre/correo antes del POST, recorta espacios y distingue error de validación, error del servidor y falta de conexión. La validación del backend se mantiene intacta.
- Nuevo fixture dinámico aislado `tests/visual/profile-validation-fixture.mjs`: tres escenarios (correo inválido, desconexión y 503), sin modificar perfiles reales. Integrado en runner visual. Pruebas completas aprobadas.
- Pendiente: pruebas de Cuenta autenticadas y revisión de accesibilidad del selector de avatar y formularios.

## Duodécima revisión: etiquetas accesibles en Cuenta (2026-10-08)

- Los cinco campos de Perfil/Seguridad tenían etiquetas `<label>` sin `for`, por lo que su relación accesible no estaba explícita.
- Se añadieron asociaciones `for`/`id`, anuncios `role=status` con `aria-live=polite` en los dos mensajes de estado y nombre accesible para el selector de avatar.
- Fixture estático `tests/visual/account-accessibility-fixture.mjs` verifica presencia de atributos en el HTML real; integrado al runner visual. No equivale a una auditoría completa con lector de pantalla.
- Pendiente: comprobación manual con teclado y lector de pantalla en sesión autenticada; revisión global de contraste y accesibilidad.

## Decimotercera revisión: evidencia incompleta de servicios (2026-10-08)

- `loadServerStatus` omitía silenciosamente servicios ausentes; con objeto de servicios vacío podía indicar erróneamente «Todos los componentes operativos».
- Ahora incluye los servicios esperados aunque falte su evidencia, marcándolos para atención; en ausencia completa de evidencia limpia la cuadrícula y el resumen anterior.
- Fixture estructural `tests/visual/services-evidence-fixture.mjs` verifica los guards sobre el código real; integrado al runner visual. No es una prueba dinámica del navegador autenticado.
- Pendiente: validar visualmente estados de servicios parciales con mocks de navegador y revisar los demás estados de carga en Servidor.

## Decimocuarta revisión: invalidación de servicios tras error de lectura (2026-10-08)

- `loadServerStatus` limpiaba metadatos de base de datos ante excepción, pero podía conservar filas y resumen de servicios previos como si fueran actuales.
- El manejador de error ahora borra las dos vistas de servicios, marca la evidencia como no confirmada y actualiza la fecha de observación a estado no verificable.
- Fixture estructural `tests/visual/services-error-reset-fixture.mjs` comprueba los resets en el bloque de error real; integrado al runner visual. No se provocó una caída de servicios productivos.
- Pendiente: prueba dinámica de error de red en navegador simulado y revisión de otros KPIs obsoletos de Servidor.

## Decimoquinta revisión: indicadores de protección sin evidencia (2026-10-08)

- El panel de Journal/binlogs marcaba las protecciones como no verificables en respuestas incompletas y errores, pero retenía barras, valores y fecha de una lectura anterior.
- Se limpian barras de uso, cifras y hora de observación en ambos casos, además de mostrar el estado de protección no verificable. No se modificó configuración ni datos de Journal o MySQL.
- Fixture estructural `tests/visual/protection-error-reset-fixture.mjs` verifica ambos caminos en el código real; integrado al runner visual. Pruebas generales y visuales aprobadas.
- Pendiente: prueba dinámica en navegador con respuesta parcial simulada y auditoría de otros indicadores de Servidor.

## Decimosexta revisión: métricas agregadas de flota sin evidencia (2026-10-08)

- `loadServerStatus` limpiaba solo tres contadores al recibir un bloque `database.devices` inválido, conservando otros KPIs, porcentajes, estados y salud de flota de una lectura anterior; en excepciones no limpiaba la flota.
- Se creó `clearFleetSnapshot()` y se aplica tanto a evidencia parcial como al error de consulta; restablece contadores, actividad, porcentajes, barras, estado de salud y fecha de observación a no verificables.
- Fixture dinámico aislado `tests/visual/fleet-error-reset-fixture.mjs` ejecuta el helper real con valores obsoletos simulados y verifica ambos puntos de llamada. La primera versión del test verificaba erróneamente `textContent` en un contenedor de clase, se corrigió y se ejecutaron nuevamente todas las pruebas con éxito.
- No se consultaron ni alteraron datos individuales GPS. Pendiente: comprobar estado parcial en navegador simulado y validar consistencia de otras métricas.

## Decimoséptima revisión: sincronización de avatar entre perfil y menú (2026-10-08)

- `loadAccountProfile` ocultaba el avatar principal cuando `has_avatar=false`, pero dejaba visible la imagen anterior en el menú de cuenta y sus callbacks de carga.
- Ahora oculta ambos avatares, muestra las iniciales en ambos lugares y desactiva callbacks de imágenes anteriores cuando no existe foto.
- Fixture dinámico `tests/visual/avatar-drawer-reset-fixture.mjs` ejecuta la función real con perfiles simulados con y sin avatar; integrado al runner visual. Pruebas generales y visuales aprobadas.
- Pendiente: comprobación autenticada de Cuenta y manejo de errores de carga de imagen durante el preview.

## Decimoctava revisión: vista previa de avatar y recursos temporales (2026-10-08)

- El controlador de vista previa liberaba `URL.createObjectURL` únicamente tras `onload`, sin `onerror`, por lo que una imagen inválida podía dejar un recurso temporal retenido y sin mensaje específico.
- Se añadió limpieza idempotente de la URL temporal en `onload` y `onerror`, y un estado visible de fallo de vista previa.
- Fixture dinámico `tests/visual/avatar-preview-cleanup-fixture.mjs` ejecuta el controlador real con imágenes simuladas, comprueba liberación una sola vez por vista previa tanto en éxito como en error; integrado al runner visual.
- No se subieron imágenes reales ni se modificaron perfiles de producción. Pendiente: pruebas autenticadas de carga real y revisión de validaciones de archivos.

## Decimonovena revisión: activación por teclado del avatar (2026-10-08)

- El selector de avatar usaba una etiqueta que contenía un input oculto, sin foco ni activación accesible mediante teclado.
- Se añadió `role=button`, `tabindex=0` y activación mediante Enter o Espacio, sin interceptar Tab.
- Fixture dinámico `tests/visual/avatar-keyboard-fixture.mjs` verifica teclado y foco; integrado al runner visual. La primera ejecución visual detectó interferencia con extracción de un fixture anterior; se reubicó el controlador y la batería visual completa pasó en la segunda ejecución. Pruebas aisladas 338 aprobadas, 9 omitidas.
- Pendiente: comprobación manual con lector de pantalla y teclado en navegador autenticado.

## Vigésima revisión: carrera entre vista previa y respuesta de avatar (2026-10-08)

- La limpieza de `URL.createObjectURL` dependía de `onload/onerror`, pero `loadAccountProfile()` reemplazaba esos callbacks si el servidor respondía antes que el evento de imagen.
- Se invoca `releasePreview()` antes de refrescar el perfil tanto en éxito como en error HTTP o de red; la liberación sigue siendo idempotente.
- Fixture dinámico `tests/visual/avatar-preview-race-fixture.mjs` reproduce las tres respuestas rápidas y comprueba la liberación previa al refresco. Runner visual y batería aislada completos aprobados.
- No se modificaron fotografías ni cuentas reales. Pendiente: prueba autenticada de carga de avatar y revisión de otros flujos asíncronos.

## Vigesimoprimera revisión: tipo de archivo de avatar (2026-10-08)

- El `accept` del selector no garantizaba que el manejador de cambio rechazase tipos ajenos a PNG, JPG o WebP antes de crear vista previa y enviar la solicitud.
- Se añadió validación local de MIME declarado y mensaje específico antes de asignar una URL temporal o realizar POST. Se conservan las validaciones de tamaño y del servidor.
- Fixture dinámico `tests/visual/avatar-filetype-fixture.mjs` prueba tipos no admitidos y permitidos; se actualizaron fixtures previos para incluir MIME simulado. Runner visual y pruebas aisladas completas aprobadas.
- La validación local no acredita seguridad del contenido binario; pendiente revisión de validación del backend y pruebas autenticadas sin modificar cuentas reales.

## Vigesimosegunda revisión: validación de estructura WebP en backend (2026-10-08)

- `save_avatar` y `read_avatar` aceptaban WebP solo por la firma `RIFF`/`WEBP`, sin comprobar tamaño RIFF declarado ni el tipo de bloque inicial.
- Se añadió `_valid_webp_header`, que exige cabecera de longitud suficiente, longitud RIFF coherente y bloque inicial VP8, VP8L o VP8X; se aplica tanto en escritura como lectura.
- `tests/test_avatar_webp_header.py` cubre cabeceras admitidas, truncadas, con bytes extra, longitud incorrecta y bloques no admitidos. Suite aislada: 340 aprobadas, 9 omitidas, 78 subpruebas. Visual completa aprobada.
- Se intentó ejecutar `python3 -m pytest` del sistema, que no tiene pytest; se usó el runner aislado oficial del proyecto y aprobó. Validación de cabecera no sustituye un decodificador completo. No se modificaron avatares reales.

## Vigesimotercera revisión: longitudes de bloques RIFF WebP (2026-10-08)

- La comprobación WebP previa validaba longitud global y primer FourCC, pero aceptaba tamaños internos de bloque incompatibles con el contenido real.
- `_valid_webp_header` recorre ahora los bloques RIFF, valida cabeceras de 8 bytes, tamaño declarado y relleno de alineación, rechazando truncamientos y sobras.
- Se ampliaron pruebas `tests/test_avatar_webp_header.py` con tamaños internos alterados y relleno impar; batería aislada 341 aprobadas, 9 omitidas y 78 subpruebas, visual completa aprobada.
- Sin cambios en datos reales; sigue pendiente decodificación completa y prueba autenticada de carga de imágenes.

## Vigesimocuarta revisión: firma PNG consistente en lectura de avatar (2026-10-08)

- `save_avatar` exigía los ocho bytes de firma PNG, pero `read_avatar` devolvía como PNG cualquier archivo con prefijo de cuatro bytes `\x89PNG`.
- `read_avatar` exige ahora la firma completa antes de servir el archivo como `image/png`, coherente con la escritura.
- Dos pruebas nuevas con archivos temporales y monkeypatch verifican rechazo de PNG incompleto y conservación de PNG/JPEG admitidos; pruebas aisladas 343 aprobadas, 9 omitidas y 78 subpruebas, visual completa aprobada.
- Se mantuvieron intactos archivos de cuentas reales. Pendiente decodificación profunda de imágenes y pruebas autenticadas.

## Revisión 25: escritura concurrente de cuenta

Se sustituyó el temporal compartido por temporales únicos con permisos 0600 y limpieza ante errores. Dos pruebas nuevas verifican concurrencia y fallo de reemplazo. Suite: 345 aprobadas, 9 omitidas, 78 subpruebas; visual completa aprobada. Sin datos reales modificados.

## Revisión 26: tamaño mínimo de avatar al leer

Se unificaron los límites de lectura y escritura de avatar (16 bytes a 2 MiB), con regresión de PNG y JPEG diminutos. Suite: 346 aprobadas, 9 omitidas, 78 subpruebas; visual completa aprobada. No se modificaron datos reales.

## Revisión 27: durabilidad de escrituras de cuenta

Se sincroniza el directorio después de reemplazar el archivo de cuenta. Nueva prueba de fsync en archivo y directorio. Suite: 347 aprobadas, 9 omitidas, 78 subpruebas; visual completa aprobada. Sin datos reales modificados.

## Revisión 27: relleno RIFF de bloques WebP

Se valida el byte cero de relleno en bloques RIFF de longitud impar. Prueba de regresión con relleno válido e inválido. Suite aislada: 348 aprobadas, 9 omitidas y 78 subpruebas; visual completa aprobada. Sin cambios de datos reales.
