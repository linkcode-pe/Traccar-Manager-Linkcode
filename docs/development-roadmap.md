# Hoja de ruta de desarrollo

Las fases son una planificación; no implican que estén implementadas ni autorizadas por este documento.

1. **FASE 1 — Estructura y repositorio.** Crear la raíz, documentación y control de versiones.
2. **FASE 2 — Auditoría del servidor y detección segura.** Inventariar y reportar sin modificar.
3. **FASE 3 — Dashboard web.** Diseñar e implementar después de aprobar requisitos y controles.
4. **FASE 4 — Administración de Traccar.** Integración controlada, con privilegios mínimos.
5. **FASE 5 — Mantenimiento y limpieza segura.** **EN PROGRESO.** DETECTAR, PREVISUALIZAR, CLASIFICAR y CONFIRMAR ya cuentan con flujo web/Worker auditado, autorización one-shot, anti-replay y revalidación. **RESPALDAR** y la verificación posterior siguen pendientes; por ello **ELIMINAR permanece bloqueado con `DENY_PRODUCTION`**. Secuencia obligatoria: **DETECTAR → PREVISUALIZAR → CLASIFICAR → CONFIRMAR → RESPALDAR → ELIMINAR → VERIFICAR**. Nunca borrar automáticamente.
6. **FASE 6 — Integración controlada con base de datos.** Diseñar controles antes de cualquier acceso; no habilitar SQL arbitrario.
7. **FASE 7 — Instalador web.** Diseñar y validar antes de hacerlo funcional.
8. **FASE 8 — Empaquetado para servidores externos.** Definir compatibilidad, instalación, actualizaciones y recuperación.
9. **FASE 9 — Plugin/integración futura con Traccar.** Evaluar como evolución separada, sin mezclarlo con la instalación existente.
