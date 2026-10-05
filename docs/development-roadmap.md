# Hoja de ruta de desarrollo

Esta hoja de ruta mantiene una sola dirección de producto: **Traccar Manager Linkcode será una plataforma/plugin web reutilizable para administrar Traccar y sus recursos relacionados, no un administrador general de Linux.**

## Completado / baseline

1. **FASE 1 — Estructura y repositorio.** Estructura, documentación inicial y control de versiones.
2. **FASE 2 — Inventario y diseño seguro.** Clasificación de componentes, límites de privilegios y contratos iniciales.
3. **FASE 3 — Baseline Manager seguro.** Dashboard web, autenticación/sesiones, RBAC, Worker no-root, UDS, auditoría y primer proveedor real `traccar.status.read`. Snapshot validado en `phase3/validated-manager`.

## Siguientes fases

4. **FASE 4 — Centro de mantenimiento.** Llevar al dashboard operaciones predefinidas de diagnóstico, previsualización y limpieza/retención de logs y archivos relacionados con Traccar. Integrar los scripts existentes detrás de Worker + RBAC + auditoría; nunca shell arbitrario desde la web.
5. **FASE 5 — Mantenimiento de datos Traccar.** Previsualizar y ejecutar políticas de retención de posiciones/datos obsoletos con límites, confirmación, verificación y recuperación. No habilitar SQL arbitrario.
6. **FASE 6 — Administración Traccar.** Accesos rápidos y flujos controlados para usuarios, vehículos/dispositivos y relaciones necesarias. Preferir interfaces de Traccar cuando sean adecuadas; cualquier acceso directo a datos deberá estar explícitamente diseñado y limitado.
7. **FASE 7 — Dashboard operativo unificado.** Historial de tareas, resultados, auditoría, estados y controles de mantenimiento en una interfaz coherente.
8. **FASE 8 — Instalador guiado.** Detectar entorno, validar requisitos, solicitar configuración necesaria, instalar servicios/configuración de Manager y comprobar salud sin incorporar secretos al repositorio.
9. **FASE 9 — Portabilidad y releases.** Empaquetado, compatibilidad con servidores Traccar externos, upgrades, rollback y documentación de operación.

## Regla para operaciones destructivas

Toda función de limpieza debe conservar el ciclo:

**DETECTAR -> PREVISUALIZAR -> CLASIFICAR -> CONFIRMAR -> RESPALDAR -> EJECUTAR -> VERIFICAR -> AUDITAR**

La automatización puede simplificar pasos operativos, pero no eliminar las fronteras de autorización ni convertir el Manager en una consola administrativa irrestricta.

## Regla de entrega

GitHub es la referencia del código. Cada fase relevante debe actualizar esta documentación, ejecutarse en rama, pasar sus pruebas/gates y revisarse antes de integrarse a `main`.
### Regla transversal de interfaz

Toda interfaz nueva o existente de Traccar Manager debe conservar el sistema visual derivado del `/panel` original: dashboard administrativo oscuro, tarjetas compactas, acento cian, estados claros y responsive. La identidad visual no altera las fronteras de seguridad ni incorpora al Manager el acceso directo a datos usado por el panel histórico.
