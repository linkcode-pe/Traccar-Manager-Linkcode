# Traccar Manager Linkcode

**Estado actual:** baseline Phase 3 validado. El Manager web, autenticación/RBAC, Worker no-root, transporte UDS, auditoría encadenada y el proveedor inicial de estado de Traccar están implementados y validados. La administración de datos, usuarios, vehículos y las operaciones de limpieza desde el dashboard siguen siendo fases posteriores y deben incorporarse mediante operaciones explícitas y auditables.

## Visión permanente

Traccar Manager Linkcode es una plataforma web independiente y reutilizable para administrar instalaciones Traccar. Su objetivo no es administrar Linux de forma general: su alcance es Traccar, sus datos y los recursos operativos relacionados que el Manager declare expresamente.

La meta del producto es poder instalarlo en este servidor y, posteriormente, llevarlo a otros servidores Traccar mediante un instalador guiado, manteniendo el mismo modelo de permisos, validación, auditoría y recuperación.

## Capacidades objetivo

- Dashboard de diagnóstico y estado de Traccar.
- Ejecución controlada de tareas de mantenimiento desde la web.
- Limpieza y retención de posiciones/datos obsoletos de Traccar mediante operaciones predefinidas; nunca SQL arbitrario desde la interfaz.
- Limpieza y retención de logs de Traccar y otros archivos relacionados previamente clasificados como seguros para mantenimiento.
- Accesos rápidos para crear y administrar usuarios de Traccar.
- Consulta y administración controlada de vehículos/dispositivos y relaciones asociadas.
- Historial y auditoría de las acciones administrativas.
- Instalación, configuración y actualización reproducibles en servidores externos.

## Arquitectura de seguridad

La web no recibe privilegios generales de root. Las operaciones privilegiadas o sensibles deben atravesar contratos explícitos y una allowlist:

```text
Usuario -> Manager Web -> autenticación/RBAC -> UDS -> Worker no-root
                                                |          |
                                                |          +-> operación permitida
                                                |          +-> auditoría
                                                v
                                           fail-closed
```

El proveedor `traccar.status.read` es la primera operación real validada de extremo a extremo. Su propósito fue demostrar la arquitectura Web -> RBAC -> UDS -> Worker -> systemd read-only -> auditoría; no representa el límite funcional del producto.

## Mantenimiento seguro

Las operaciones destructivas deben seguir el ciclo **DETECTAR -> PREVISUALIZAR -> CLASIFICAR -> CONFIRMAR -> RESPALDAR -> EJECUTAR -> VERIFICAR -> AUDITAR**. No se habilitará una consola SQL arbitraria ni borrado genérico del filesystem desde el dashboard.

Los scripts existentes de estado y retención constituyen referencias/operaciones que deberán integrarse progresivamente detrás del Worker y RBAC, no ejecutarse directamente por el navegador.

## Estado Phase 3

El baseline validado incluye API y contratos, Manager web, autenticación y sesiones, RBAC, Worker, UDS, ledger de auditoría, proveedor de estado de Traccar, configuración de despliegue, interfaz web, scripts existentes y pruebas automatizadas. La rama de validación es `phase3/validated-manager`.

## GitHub y documentación viva

GitHub es la fuente de referencia del código. El desarrollo debe avanzar mediante ramas, revisión, pruebas y commits controlados antes de integrar a `main`. La documentación del repositorio es documentación viva: debe actualizarse con cada avance relevante para reflejar el estado real y las decisiones vigentes.

## Separación y secretos

Traccar, Traccar Manager, configuración sensible, datos, logs y backups permanecen separados. Nunca versionar credenciales, claves privadas, tokens, dumps, logs sensibles ni configuración secreta.

Consulta `docs/architecture-overview.md`, `docs/development-roadmap.md`, `docs/project-structure.md` y los documentos específicos de seguridad/auditoría para el diseño detallado.

La licencia permanece pendiente de decisión del propietario; `LICENSE` no debe interpretarse como concesión de una licencia hasta que se defina expresamente.
## Dirección de producto V1

El alcance rector está en `docs/product-master-v1.md` y el estado modular en `docs/v1-module-status.md`.
