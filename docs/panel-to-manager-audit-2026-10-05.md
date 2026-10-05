# Auditoria Panel a Manager - 2026-10-05

## Veredicto
Panel legacy queda retirado como producto y plano de control. Manager es la unica interfaz objetivo. Los artefactos fisicos legacy permanecen solo como rollback inactivo hasta retiro controlado. Los timers Panel, logs 30d y retencion DB 90d estan disabled/inactive.

## Clasificacion
| Capacidad legacy | Estado | Destino | Decision |
|---|---|---|---|
| PHP/assets `/panel/` | RETIRABLE | Manager UI | No ejecutar/evolucionar; ruta publica redirige a `/manager/`. |
| Login/sesion PHP y config Panel | REEMPLAZADO | `manager/auth` | Manager ya tiene auth/sesion/RBAC; no migrar credenciales legacy. |
| htpasswd Panel | RETIRABLE | Auth Manager | No copiar hashes/secretos. |
| status script/service/timer Panel | REEMPLAZADO | `traccar.status.read` | Manager-UDS-Worker-audit sustituye el patron; timer apagado. |
| Estilo visual Panel | MIGRADO | Manager UI | Conservado sin dependencia runtime de `/panel`. |
| Metricas disco raiz | PENDIENTE | M1 read-only | Integrar provider fijo; Web no lee filesystem. |
| Conteos `tc_devices` | PENDIENTE | M5 read-only | Provider/API allowlisted; no PDO/SQL en Web. |
| Posiciones actuales | PENDIENTE | M5/M3 read-only | RBAC y minimizacion por uniqueid/coordenadas/direccion. |
| Metricas `tc_positions` | PENDIENTE | M3 read-only | Provider DB read-only aprobado. |
| Posiciones antiguas >90d | PENDIENTE | M3 Preview | Redisenar como preview de retencion. |
| Script/timer logs 30d | REEMPLAZADO_PARCIAL | M2 logs | Preview/Prepare existen; Execute no. No reactivar script. |
| Estado legacy logs 30d | RETIRABLE_DESPUES_M2 | M7 audit/tareas | Sustituir por audit/receipts Manager. |
| Script/timer DB 90d | PENDIENTE_CRITICO | M3 data retention | No portar DELETE literal. Disenar preview, backup/recovery, RBAC, audit e idempotencia. |
| Estado legacy DB 90d | RETIRABLE_DESPUES_M3 | M7 audit/tareas | Sustituir por historial Manager. |
| Scripts administrativos autonomos futuros | RETIRABLE_COMO_PATRON | Manager/Worker/Scheduler | No crear nuevos timers/scripts root fuera de Manager. |

## Hallazgos
1. Panel abre MySQL directamente desde PHP con `panel_readonly`; ese patron no se migra.
2. Panel lee filesystem/archivos de estado al renderizar; se sustituye por providers/DTO allowlisted.
3. La vista de posiciones expone uniqueid, coordenadas y direccion; requiere permiso especifico y minimizacion.
4. El script logs 30d contiene borrado directo. Queda sustituido por M2 Preview -> Prepare -> futura confirmacion/Execute auditada.
5. El script DB 90d ejecuta DELETE sobre `tc_positions` por lotes. Es el legado de mayor riesgo: no reactivar ni portar literalmente.
6. La limpieza automatica queda temporalmente detenida de forma intencional hasta existir equivalente Manager seguro.

## Orden aprobado
1. Terminar M2 logs y luego Scheduler Manager opcional.
2. Integrar disco read-only en M1.
3. M5 read-only para dispositivos/posicion minimizada.
4. M3 read-only antes de retencion DB.
5. Disenar M3 retencion 90d desde cero.
6. Retirar cada legado solo despues de reemplazo verificado.

## Gate de retiro fisico
Eliminar solo cuando este inactivo, sin consumidores, reemplazado o descartado, con rollback temporal, ruta publica fuera de servicio, documentacion/Git actualizados y verificacion posterior de Manager/Worker/Traccar.
