# Identidad Web→API y bloqueo del gateway — fase v2

## Precheck y límites

Conexión SSH al host autorizado y huella verificada; raíz `/opt/traccar-manager/`, rama `master`. `git status` fue solo lectura. Los seis hashes de `web/` coinciden con los valores autoritativos. No se inició ningún proceso ni listener.

No se leyeron archivos protegidos, cookies, tokens, contraseñas, credenciales de DB ni secretos. No se modificó la web ni componentes existentes. La operación de auditoría descrita abajo se detuvo antes de implementar por la regla de no modificar el Dispatcher existente sin autorización.

## Identidad Web→API

El análisis estático previo, confirmado por los hashes, muestra que `login.php` crea datos de sesión después de `password_verify`; `index.php` incluye `/etc/traccar-panel/session_guard.php`, y `logout.php` destruye la sesión. No se inspeccionó `auth.php` ni `session_guard.php`; por tanto no se afirma cuál es la regla exacta de vigencia, revocación o expiración de la sesión actual.

`api/web_session_identity_v1.py` es un contrato de salida para un **futuro** verificador confiable:

```text
WEB SESSION (validada server-side)
→ VerifiedIdentity(issuer, subject_id opaco)
→ resolución de roles server-side
→ operación fija dashboard.snapshot.read.v1
→ rol mínimo dashboard.read
```

`WebSessionEvidence` solo representa el resultado de ese verificador y excluye `role`, `permissions`, `user_id` del cliente, cookie, token y password. La API no acepta esos campos ni confía en JavaScript. No se implementó autenticación HTTP ni verificación criptográfica: el assertion de red, su integridad, caducidad y replay protection necesitan una decisión posterior y no incluyen secretos en esta fase.

Errores estables: `API_UNAUTHORIZED` para sesión ausente, inválida o expirada; `API_FORBIDDEN` para rol insuficiente u operación no permitida; `API_INTERNAL_ERROR` para configuración/integración inválida. La distinción interna de estado no revela detalles de sesión al cliente.

## Gateway de auditoría: detenido antes de cambios

La inspección estática de `worker/dispatcher/__init__.py` confirma que su única operación allowlisted es `traccar.status`, con rol `traccar.status.read`, target fijo `systemd-unit:traccar.service` y payload vacío. No existe `dashboard.snapshot.read.v1` en su allowlist.

La API necesita auditoría para `dashboard.snapshot.read.v1`. Escribir eventos directamente con `AuditLedger.append()` desde un adapter API sería un bypass del Dispatcher; reutilizar `traccar.status` mentiría sobre la operación y su target. Además, el sink API actual no devuelve un recibo durable, mientras el ledger requiere contexto de job/operation/target y verifica `AppendReceipt` y la hash chain.

Por ello **no se implementó ni conectó un gateway durable** y no se intentó simular receipts. Para hacerlo de forma real, primero se necesita autorización explícita para una ampliación acotada de `worker/dispatcher/__init__.py`: registrar `dashboard.snapshot.read.v1` con rol, target y payload estrictamente fijos y un flujo de auditoría/receipt compatible. También puede requerirse adaptar `api/read_only_dashboard_v1.py` para exigir y verificar receipt durable al finalizar. Riesgo: cambia la superficie allowlisted y el ciclo de autorización/idempotencia; no debe hacerse como simple append directo.

Antes de esa autorización, no se puede afirmar que el gateway de dashboard impida doble consumo, deduplique request_id o emita/verifique recibos propios. Las pruebas existentes del ledger/dispatcher cubren sus componentes aislados, no esta integración inexistente.

## Pruebas de identidad

`tests/test_web_session_identity_v1.py` usa identidades y resolvers ficticios para estado válido, ausente, inválido, expirado, rol válido/insuficiente, operación no permitida, campos no aceptados y códigos estables. No consulta PHP, HTTP, Dispatcher real, ledger, MySQL ni producción.

## Siguiente autorización requerida

Autorizar por separado, antes de editar, el cambio exacto en `worker/dispatcher/__init__.py` y cualquier cambio indispensable en `api/read_only_dashboard_v1.py`, limitado a soportar la operación allowlisted de lectura y su receipt durable con tests locales. Esa autorización no implicaría conectar proveedores, publicar endpoint ni modificar web/Apache/producción.
