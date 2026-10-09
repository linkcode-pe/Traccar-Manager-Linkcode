# PLAN MAESTRO — TRACCAR MANAGER LINKCODE

**Versión:** 2.3 (primer despliegue prioriza el Centro de Desarrollo y Progreso)
**Fecha:** 2026-10-09  
**Estado:** Documento de planificación. No representa funcionalidades implementadas ni autorización de despliegue.

## 1. Visión y límites

Traccar Manager debe ser una plataforma de administración y supervisión profesional, segura, estable y fácil de usar, que complemente al servidor GPS oficial de Traccar sin alterar su núcleo ni comprometer sus servicios. El despliegue actual `https://homecargps.com/manager/` es la referencia operativa. El repositorio `linkcode-pe/Traccar-Manager-Linkcode` se utiliza como respaldo del código y documentación técnica; no debe convertirse en un despliegue paralelo.

Las nuevas funcionalidades requieren diagnóstico, diseño, desarrollo aislado, pruebas, revisión y autorización expresa antes de instalarse en producción. No ejecutar borrados de registros, operaciones de base de datos, reinicios ni cambios en Traccar oficial sin autorización específica.

## 2. Requisitos funcionales confirmados por el propietario

### COM — Bot de WhatsApp

**Propósito principal:** enviar automáticamente a los números de WhatsApp de los clientes las **alertas oficiales que Traccar genere para los dispositivos GPS asociados a cada cliente**, y permitir **conversaciones básicas** mediante mensajes y respuestas configurados en un apartado administrativo del bot.

**Administración exclusiva:** solo el administrador autorizado configura el bot. Los clientes no configuran reglas, números, eventos ni respuestas desde su cuenta.

**Flujo funcional:**
1. Traccar emite un evento oficial de un dispositivo.
2. Traccar Manager recibe el evento por una integración autorizada y verifica su autenticidad.
3. El sistema identifica la relación vigente entre dispositivo y cliente.
4. Comprueba que el número del cliente esté autorizado y tenga consentimiento válido para recibir mensajes.
5. Aplica las reglas que configuró el administrador: tipos de evento, destinatarios, mensajes y condiciones de envío.
6. Envía la notificación mediante un proveedor o API de WhatsApp autorizado y registra el resultado.
7. Para mensajes entrantes, utiliza respuestas básicas o flujos de conversación definidos por el administrador, sin permitir consultar dispositivos ajenos ni ejecutar operaciones peligrosas.

**Casos principales:**
- Un cliente con varios dispositivos puede recibir alertas de todos los dispositivos que tenga asociados y autorizados.
- Un dispositivo nunca debe enviar datos a un cliente que ya no tenga acceso a él.
- Un mismo evento debe evitar notificaciones duplicadas mediante idempotencia.
- Si el proveedor falla, registrar error y aplicar reintentos limitados con controles de frecuencia.
- La configuración y el historial deben estar disponibles para el administrador, con control de acceso y auditoría.

**Pantalla administrativa prevista:** conexión del proveedor, estado operativo, números y consentimiento, relación cliente-dispositivo, eventos habilitados, plantillas de mensajes, respuestas básicas, horarios y reglas, historial de entrega y fallos, pruebas controladas y auditoría.

**Requisitos de privacidad y cumplimiento:** no exponer números o credenciales en logs, proteger tokens, respetar permisos y bajas, y cumplir las políticas de WhatsApp, incluidas plantillas aprobadas y ventanas de conversación cuando sean aplicables. La integración concreta aún debe seleccionarse.

**Pendiente de especificación:** proveedor oficial elegido, conjunto exacto de eventos habilitados, reglas de horario, contenido de plantillas, política de consentimiento y retención, costes, límites y diseño detallado de conversaciones. No asumirlos como decisiones ya aprobadas.

### PROG — Centro de Desarrollo y Progreso

**Requisito obligatorio confirmado por el propietario:** la web de Traccar Manager tendrá un **checklist interactivo y completo de todo el proceso de construcción y evolución del proyecto**, visible exclusivamente para el superadministrador en el **Centro de Desarrollo y Progreso**. Debe mostrar cómo queremos que funcione Traccar Manager, qué está implementado, qué falta y qué está validado; no será solo una lista estática de ideas.

**Estructura del checklist:** fases > módulos > funcionalidades > tareas y subtareas verificables, incluyendo AUD, SEC, BCP, PROG, DOC, ADM, OPS, TEO y COM (bot de WhatsApp). Cada elemento debe tener identificador estable, descripción, criterios de aceptación, prioridad, responsable cuando corresponda, dependencias, fecha de actualización y referencias a evidencias.

**Estados:** pendiente, en desarrollo, en pruebas, bloqueado y completado/verificado. Solo se marcará como completado cuando se cumplan criterios de aceptación y existan pruebas o evidencias verificables. El estado de una tarea no se deduce exclusivamente de la existencia de código o de una afirmación del asistente.

**Interfaz:** vista general con progreso global y por fase/módulo; secciones expandibles; casillas de verificación; filtros por estado, prioridad y módulo; búsqueda; detalle de cada tarea con historial, decisiones, pruebas, commits y despliegues; alertas de bloqueos y pendientes. La información debe conservarse entre sesiones y permitir seguimiento de nuevas funcionalidades que se añadan al Plan Maestro.

**Cálculo del avance:** porcentaje basado en tareas verificadas frente a tareas elegibles definidas, con denominador visible, reglas documentadas y tratamiento explícito de tareas bloqueadas/no aplicables. Si no existe evidencia suficiente, mostrar «sin verificar» en vez de inventar un porcentaje. No mostrar barras ilustrativas como datos reales.

**Gobernanza:** solo el superadministrador puede consultar y gestionar este centro; los cambios de estado deben tener auditoría y no pueden eludir la validación técnica. El checklist no autoriza por sí mismo cambios de producción ni operaciones peligrosas.

**Criterios de aceptación:** (1) están representados todos los objetivos aprobados del Plan Maestro; (2) las tareas pueden desplegarse por fases y consultarse individualmente; (3) los estados persisten y están auditados; (4) ninguna tarea se completa sin evidencia; (5) el avance se recalcula de forma consistente; (6) los permisos impiden acceso de usuarios no autorizados; (7) las nuevas indicaciones aprobadas pueden añadirse sin perder historial.

### Hito D1 — Primer despliegue: Centro de Desarrollo y Progreso

**Decisión aprobada por el propietario (2026-10-09):** el primer despliegue funcional del nuevo desarrollo debe incluir el Centro de Desarrollo y Progreso, con el checklist del Plan Maestro visible dentro de Traccar Manager. Esta prioridad de entrega sustituye el orden secuencial inicial de las fases, **sin omitir las verificaciones de seguridad, respaldos y recuperación que condicionan el despliegue**.

**Alcance mínimo de D1:** acceso exclusivo de superadministrador validado en el servidor; listado íntegro de fases, módulos, tareas y subtareas; estados persistentes y auditables; búsqueda y filtros; detalle de criterios, dependencias, evidencias, pruebas, commits y documentación DOC-001; cálculo de progreso real y verificable; interfaz compatible con móvil y escritorio. Ninguna casilla puede completarse por una simple acción visual sin evidencia y autorización apropiada.

**Secuencia de entrega:** D1.1 especificar esquema de datos, roles y fuente documental; D1.2 implementar API y persistencia seguras; D1.3 integrar la interfaz al sitio existente; D1.4 pruebas de autorización, aislamiento, consistencia, regresión y respaldo/restauración; D1.5 documentación y paquete de despliegue reversible; D1.6 aprobación explícita del propietario antes de instalar; D1.7 verificación posterior a instalación.

**Exclusiones del primer despliegue:** no implica habilitar administración de dispositivos, envío de WhatsApp ni cambios en Traccar oficial. SEC-009 sigue como trabajo en desarrollo independiente; sus riesgos relevantes deben revisarse como condición de seguridad para D1. GitHub conserva documentación y respaldos; no publicar código experimental en la rama principal como si fuera producción.

**Estado del hito:** aprobado como prioridad; desarrollo y despliegue pendientes. No equivale a autorización para modificar producción.

### Operación y protección

Interfaz administrativa moderna, segura y comprensible. Separación del Traccar oficial. GitHub como respaldo y registro documental. Autonomía de desarrollo en entornos aislados; producción solo con autorización expresa.

### DOC-001 — Documentación viva y actualización obligatoria

**Requisito obligatorio confirmado por el propietario:** Traccar Manager debe contar con documentación funcional y técnica versionada, que se mantenga **actualizada con cada cambio del proyecto**. La documentación es parte del entregable, no una actividad opcional posterior.

**Cobertura mínima según el tipo de cambio:**

- **Funcional:** objetivos, comportamiento, pantallas, procedimientos de uso y limitaciones de cada módulo.
- **Técnica:** arquitectura, contratos API, integraciones con Traccar oficial, modelos de datos, dependencias y configuración no secreta.
- **Seguridad:** permisos, autenticación, auditoría, protección de datos y decisiones de riesgo.
- **Operación:** instalación, actualizaciones, respaldos, recuperación, rollback y diagnósticos.
- **Evolución:** registro de cambios, versiones, incidencias relevantes, decisiones, pruebas y commits asociados.
- **Plan Maestro:** actualizar tareas, criterios de aceptación, checklist, estado y progreso del Centro de Desarrollo y Progreso.

**Regla de cierre:** ninguna actualización se considera **completada/verificada** sin documentación correspondiente actualizada, pruebas aplicables y evidencias trazables. En el checklist de cada tarea se deberá mostrar el estado documental (pendiente, en revisión, actualizado/verificado) y enlaces a sus archivos o registros. Si un cambio no requiere modificar un documento concreto, registrar una justificación revisable de «no aplica»; no simular cumplimiento.

**Control de versiones y publicación:** conservar la documentación junto al código en GitHub, mediante commits revisables. Los documentos deben identificar versión, fecha, alcance y estado; evitar credenciales, tokens y datos personales. Antes de un despliegue autorizado, comprobar que las instrucciones operativas y de recuperación corresponden a la versión a instalar. Los cambios urgentes requieren documentación y cierre posterior verificable, sin declarar el trabajo completado prematuramente.

**Criterios de aceptación:** (1) cada cambio significativo tiene documentación asociada; (2) los documentos relevantes reflejan el comportamiento probado; (3) el checklist impide marcar «completado» sin evidencia documental o justificación válida; (4) las versiones y decisiones son rastreables en GitHub; (5) se detectan y corrigen referencias obsoletas.

## 3. Líneas técnicas del Plan Maestro (propuestas sujetas a validación)

| Fase | IDs | Objetivo | Condición de cierre |
|---|---|---|---|
| 0 | AUD-001 a AUD-004 | Registro de hallazgos, línea base, responsables, aceptación y rollback | Evidencias verificables y aprobación |
| 1 | SEC-001 a SEC-009, BCP-001 a BCP-003 | Autenticación, permisos, sesiones, endurecimiento, respaldos y recuperación | Tests de regresión, restauración ensayada y revisión |
| 2 | PROG-001 a PROG-006, DOC-001 | Centro de Desarrollo y Progreso y documentación viva | Control de acceso, trazabilidad y documentación verificada |
| 3 | ADM-001/002, OPS-001/002/003 | Administración, diagnóstico y operaciones | Pruebas funcionales y controles de seguridad |
| 4 | TEO-001, COM-001 a COM-003 | Evolución técnica e integraciones, especialmente WhatsApp | Validación de privacidad, proveedor y pruebas extremo a extremo |

Los identificadores organizan el trabajo, pero no constituyen por sí mismos requisitos completos ni entregables terminados.

## 4. Prioridad del módulo COM — entregables propuestos

**COM-001 — Integración de eventos y destinatarios.** Inventariar API/eventos oficiales de Traccar; definir modelo de relaciones cliente-dispositivo-número, consentimiento y revocación; construir adaptador de eventos de solo lectura; evitar duplicados y fuga de información entre clientes.

**COM-002 — Consola administrativa del bot.** Pantalla con acceso restringido, configuración del proveedor, eventos, plantillas, respuestas básicas, reglas, destinatarios y estado. Registro de cambios y pruebas sin mensajes reales por defecto.

**COM-003 — Envío, conversaciones y observabilidad.** Adaptador de WhatsApp autorizado, procesamiento de respuestas entrantes, límites, reintentos, colas, métricas, historial, auditoría y pruebas de extremo a extremo con cuentas de prueba.

**Criterios mínimos de aceptación:** cada alerta llega solo a los destinatarios autorizados; la revocación de acceso detiene envíos; no se envían duplicados por reintentos; se respetan reglas y consentimiento; fallos quedan registrados; solo el administrador modifica configuración; no se alteran las funciones de Traccar oficial.

## 5. Auditoría y riesgos técnicos abiertos

- **AUD-002:** el repositorio fue rebasado a un respaldo del código productivo. Verificar correspondencia de archivos y trazabilidad de próximos respaldos.
- **SEC-009:** las sesiones existentes requieren revisar revocación de privilegios ante cambios de cuenta y roles. Las pruebas existentes cubren revocación individual y expiración, no revocación de todas las sesiones de una cuenta.
- **Autenticación:** revisar el comportamiento de cuentas y contraseñas en el código productivo antes de modificarlo.
- **Continuidad:** verificar respaldos restaurables, recuperación y límites de mantenimiento de logs.
- **WhatsApp:** el módulo es requisito definido, no implementación existente.

## 6. Método de ejecución

Para cada tarea: (1) diagnóstico del comportamiento actual; (2) especificación y riesgos; (3) diseño; (4) implementación aislada; (5) pruebas automatizadas y manuales; (6) evidencia de resultados; (7) revisión y aprobación; (8) despliegue autorizado; (9) verificación y rollback preparado. Ninguna fase se marca completada sin pruebas.

## 7. Decisiones pendientes del propietario

Las funciones y el alcance exactos de otros módulos administrativos, comerciales y de automatización deben recuperarse del Plan Maestro original o validarse antes de desarrollarlos. Este documento no pretende reconstruir de memoria requisitos no confirmados.

## 8. Estado de esta publicación

Publicación de **documentación únicamente**. No modifica la aplicación productiva ni implementa el bot. Al agregar este documento a GitHub, el repositorio tendrá un archivo documental adicional respecto al árbol productivo hasta el próximo respaldo sincronizado; el código de aplicación permanece idéntico a la línea base publicada.


### PROG-006 — Sincronización automática de avances (en desarrollo)

- Registrar eventos de desarrollo con identificador estable, tarea del Plan Maestro, estado, origen y evidencias.
- Aplicar idempotencia y controles de autorización y auditoría; rechazar estados verificados sin documentación/evidencia.
- Refrescar el Centro de Desarrollo automáticamente cada 15 segundos mientras esté visible.
- Conectar GitHub/CI mediante un emisor autenticado de eventos, sin permitir que un commit por sí solo marque una tarea como verificada o desplegada.
- Evidencia inicial: pruebas HTTP de permisos, origen, duplicados, persistencia y requisitos de verificación.
- **Estado:** en desarrollo; integración con GitHub/CI y validación visual aún pendientes.


## Catálogo funcional del checklist — versión 2.5 (2026-10-09)

El Centro de Desarrollo agrupa capacidades visibles para el administrador, además de tareas técnicas internas. La fuente versionada del catálogo es `manager/progress_catalog.py`, incorporada al repositorio junto a este documento. Los identificadores funcionales son estables y cada tarea conserva estado, evidencias y auditoría en SQLite.

| Módulo | Identificadores | Funcionalidades |
|---|---|---|
| Traccar oficial | TRC-001 a TRC-012 | API, vehículos, clientes, usuarios, posiciones, recorridos, eventos, geocercas, notificaciones, grupos, reportes, permisos |
| Limpieza y mantenimiento | MNT-001 a MNT-010 | MySQL, logs, archivos temporales, retención, backups, restauración, recursos y auditoría |
| WhatsApp | WAP-001 a WAP-011 | Proveedor, destinatarios, consentimiento, eventos, alertas, plantillas, respuestas, colas, historial, panel, pruebas |
| Seguridad y administración | ADM-101 a ADM-106 | Accesos, roles, sesiones, auditoría, configuración, secretos |
| Desarrollo y progreso | DEV-001 a DEV-006 | Checklist, evidencias, sincronización, CI, despliegues y documentación |

**Regla de estado:** añadir una función al catálogo no demuestra su implementación. Todas las nuevas tareas comienzan pendientes; únicamente pruebas y evidencias verificables permiten acreditarlas. Las funciones de mantenimiento se ejecutan en módulos separados, nunca desde el checklist. El sistema conserva también las 32 tareas técnicas originales para continuidad del seguimiento.
