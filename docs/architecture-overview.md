# Visión general de arquitectura

**Estado:** arquitectura base implementada y validada hasta Phase 3. Las capacidades administrativas y de mantenimiento adicionales se incorporarán progresivamente sobre esta misma frontera de seguridad.

## Objetivo

Traccar Manager Linkcode es una aplicación separada de Traccar que ofrece un panel administrativo reutilizable para operaciones relacionadas con Traccar. No pretende ser un panel de administración general del sistema operativo.

```text
[Usuario]
   |
   v
[Manager Web]
   |
   +-- autenticación / sesión
   +-- RBAC
   +-- contratos de operaciones
   |
   v
[UDS local]
   |
   v
[Worker no-root]
   |
   +-- allowlist de operaciones
   +-- validación de payload
   +-- auditoría append-only/hash-chain
   +-- adaptadores controlados
   |
   +--> estado de Traccar (implementado)
   +--> mantenimiento de logs/archivos (evolución)
   +--> retención de datos Traccar (evolución)
   +--> usuarios y vehículos Traccar (evolución)
```

## Principios obligatorios

1. La web no ejecuta shell, SQL o acciones privilegiadas arbitrarias.
2. Cada capacidad administrativa se expone como una operación definida, validada y autorizada por RBAC.
3. El Worker usa privilegio mínimo y fail-closed; ampliar funcionalidad no significa convertirlo en root general.
4. Toda operación sensible debe producir evidencia auditable y un resultado verificable.
5. Las operaciones destructivas requieren previsualización, confirmación, recuperación/backup cuando corresponda y verificación posterior.
6. Traccar y Traccar Manager conservan separación de código, configuración y datos.
7. El diseño debe ser portable: rutas, credenciales y características específicas del servidor no deben quedar codificadas como supuestos universales.

## Baseline validado

Phase 3 validó el flujo real para `traccar.status.read`: Manager/RBAC -> UDS -> Worker -> lectura systemd -> ledger compartido y recibo verificable. Este proveedor es la prueba inicial del modelo de ejecución, no el objetivo final del Manager.

Las siguientes capacidades reutilizarán esta arquitectura en lugar de otorgar acceso directo del navegador a MySQL, filesystem o systemd.