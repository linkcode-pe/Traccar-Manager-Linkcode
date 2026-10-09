# PLAN MAESTRO — TRACCAR MANAGER LINKCODE

**Versión:** 2.0 (actualización de requisitos)  
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

Panel accesible exclusivamente para superadministradores, con módulos, tareas, prioridades, estados, responsables, evidencias de pruebas, commits, decisiones, aprobaciones, incidentes y despliegues. Los porcentajes de avance solo se muestran cuando están respaldados por criterios medibles; no inventar progreso.

### Operación y protección

Interfaz administrativa moderna, segura y comprensible. Separación del Traccar oficial. GitHub como respaldo y registro documental. Autonomía de desarrollo en entornos aislados; producción solo con autorización expresa.

## 3. Líneas técnicas del Plan Maestro (propuestas sujetas a validación)

| Fase | IDs | Objetivo | Condición de cierre |
|---|---|---|---|
| 0 | AUD-001 a AUD-004 | Registro de hallazgos, línea base, responsables, aceptación y rollback | Evidencias verificables y aprobación |
| 1 | SEC-001 a SEC-009, BCP-001 a BCP-003 | Autenticación, permisos, sesiones, endurecimiento, respaldos y recuperación | Tests de regresión, restauración ensayada y revisión |
| 2 | PROG-001 a PROG-005 | Centro de Desarrollo y Progreso | Control de acceso y trazabilidad demostrados |
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
