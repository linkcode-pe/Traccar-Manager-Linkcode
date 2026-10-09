# Estado de auditoría — Traccar-Manager-Linkcode

Fecha de corte: 2026-10-09 UTC. Documento de seguimiento; no implica aprobación de despliegue.

## Identidades y conciliación AUD-002

- GitHub main: `0527e5e9ecfef4539a5092352e952ffdfde768eb`.
- GitHub phase4/maintenance-center: 78 commits delante y 1 detrás de main, 70 archivos en comparación.
- Producción `/opt/traccar-manager`: rama master, commit `a83ef92751ad0512d8e29d174a82ecd50a3ff12f`; sin remoto Git configurado.
- Se comprobaron hashes de blob diferentes entre Phase 4 y producción para README.md, manager/auth/auth_store.py, manager/web_app.py, manager/maintenance_http.py, worker/runtime_server.py, worker/retention_boundary_server.py y worker/maintenance_execute_dispatch.py.
- AUD-002 permanece ABIERTO: falta comparación exhaustiva de historias, pruebas y clasificación de diferencias.

## Hallazgos que requieren revisión

- SEC-003: la copia productiva de autenticación usa un registro global de contraseña; GitHub main y Phase 4 usan hashes por cuenta. Investigar diferencia de versión antes de corregir.
- SEC-009: SessionStore conserva roles de inicio de sesión sin revalidar cambios de permisos en cada acceso; diseñar revocación efectiva y pruebas aisladas.
- Retención: documentación Phase 4 indica autorización del propietario para eliminación de logs históricos el 2026-10-06; la configuración productiva habilita el gate, mientras documentación antigua afirma bloqueo. Reconciliar documentación y verificar controles sin ejecutar borrados.
- Continuidad: no se ha acreditado restauración completa de MySQL ni recuperación ante desastres. La evidencia SHA256 de logs no es copia restaurable.

## Objetivos del plan maestro

Fase 0: AUD-001 registro, AUD-002 conciliación, AUD-003 responsables y autorizaciones, AUD-004 criterios de recuperación y rollback.
Fase 1: SEC-001 a SEC-009 y BCP-001 a BCP-003, siempre con pruebas aisladas.
Fase 2: PROG-001 a PROG-005, Centro de Desarrollo y Progreso con acceso superadministrador y evidencia.
Fase 3: ADM-001/002 y OPS-001/002/003.
Fase 4: TEO-001 y COM-001/002/003.

## Reglas de seguridad

No hacer merge automático, no desplegar, no reiniciar servicios, no ejecutar retención de logs o SQL, no modificar `/opt/traccar-manager`, Traccar oficial ni MySQL. Todo cambio de código debe ser aislado, probado, revisado por PR y aprobado antes de despliegue.

## Próximos pasos

1. Comparar en copia aislada GitHub main, Phase 4 y árbol productivo mediante evidencia de solo lectura.
2. Revisar SEC-003 y SEC-009 con tests de regresión, sin intervención productiva.
3. Completar AUD-001 y AUD-002 con anexos verificables y plan de integración por PR.
