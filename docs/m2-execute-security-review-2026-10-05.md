# M2 Logs Execute - revision de seguridad integral - 2026-10-05

## Veredicto
**NO-GO para conectar Execute a runtime/UDS/HTTP o a `/opt/traccar/logs`.** Preview y Prepare productivos permanecen read-only/no destructivos. El helper destructivo sigue limitado a sandbox.

## Hallazgos bloqueantes

### B1 - La Preparation no tiene prueba durable de emision (CRITICO)
`LogRetentionPreparation` es un dataclass autocontenido. Execute comprueba sus campos, nonce, TTL y que preview/hash coincidan con el filesystem actual, pero no demuestra que ese `preparation_id` haya sido emitido previamente por Prepare y registrado de forma durable para el mismo actor/request. Antes de runtime se necesita un PreparationStore durable o una firma/MAC server-side; se prefiere store durable para soportar estado one-shot y auditoria.

### B2 - El consumo ocurre antes de AUDIT_PREPARE durable (ALTO)
`validate_execution_gate` puede consumir la preparation antes de que `maintenance_execute_dispatch` escriba `AUTHORIZATION_*` y `AUDIT_PREPARE`. Si la auditoria falla despues del consumo, la autorizacion queda quemada sin existir una transicion durable de ejecucion. Hay que separar `validate` de `consume`: validar -> autorizacion durable -> AUDIT_PREPARE durable -> consumo atomico -> mutacion. Si consumo y ledger no pueden compartir transaccion, debe existir estado durable reconciliable y resultado explicito para crash recovery.

### B3 - El hash de request Execute no liga nonce ni contenido completo de Preparation (ALTO)
El `parameters_hash` actual usa solo `preparation_id` y confirmation. Antes de runtime debe ligar como minimo preparation_id, preview_id/hash, retention_days, candidate_count/bytes y una huella del nonce (no el secreto en claro), ademas de identidad/operacion/target mediante authorization scope.

### B4 - Authorization de Execute es sintetica dentro del mismo dispatch (ALTO)
El dispatch de prueba crea `AUTHORIZATION_REQUESTED` y `GRANTED` durante la misma llamada. Esto sirve para probar el ledger, pero no constituye todavia una frontera real de autorizacion humana. Runtime debe aceptar solo una confirmacion autenticada/RBAC y enlazada a la preparation exacta; no debe autoconceder una capacidad destructiva por llegar al metodo.

## Hallazgos de endurecimiento

### H1 - Preview usa Path traversal previo a dirfd
Preview es read-only, pero para Execute productivo se recomienda enumeracion/revalidacion basada en descriptor del directorio y metadatos de identidad. El helper sandbox ya usa `dir_fd` para stat/unlink, pero el Preview original usa `Path.iterdir/stat`.

### H2 - mtime se reduce a segundos
El Preview serializa `mtime_utc` sin microsegundos y el helper compara por segundo. Para mutacion productiva se debe ligar `st_dev`, `st_ino`, `st_size` y `st_mtime_ns` exactos en el plan preparado, evitando una ventana de cambios dentro del mismo segundo.

### H3 - PARTIAL_DELETE necesita receipt estructurado
El helper detecta `PARTIAL_DELETE`, pero la excepcion no conserva durablemente la lista exacta ya eliminada. Un ejecutor real debe emitir receipt con deleted_names/count/bytes y candidato fallido antes de cualquier retry/reconciliacion.

### H4 - Store de consumo necesita limites/ownership para produccion
El store actual usa flock+fsync y modo 0600 al crear archivo, pero antes de produccion requiere path fijo protegido, owner/mode verificados, limite/rotacion segura y politica ante archivo demasiado grande/corrupto.

### H5 - Hook `_before_unlink` es solo test seam
No debe ser alcanzable desde parser/runtime productivo. Antes de promover el helper se separara/inoculara exclusivamente desde tests o mediante dependencia privada no serializable.

## Controles que SI pasaron
- Allowlist estricta de nombres historicos `tracker-server.log.YYYYMMDD`.
- El log activo no coincide con el patron eliminable.
- Hard-deny actual del helper sandbox para `/opt/traccar`.
- Preflight total: un cambio detectado antes de mutar produce cero deletes.
- Re-stat por dev/inode/size/mtime antes de cada unlink en sandbox.
- Symlink swap probado fail-closed.
- Candidate duplicate probado fail-closed.
- Replay del store one-shot probado fail-closed.
- TTL, nonce y preview stale probados fail-closed.
- Auditoria ledger del dispatch bloqueado pasa verificacion.

## Gates obligatorios antes de runtime destructivo
1. Crear PreparationStore durable y actor-bound; Execute solo acepta preparations emitidas por ese store.
2. Refactorizar consumo para ocurrir despues de Authorization + AUDIT_PREPARE durable y definir recovery de crash.
3. Ampliar parameters_hash/authorization scope para ligar toda la operacion sin exponer nonce.
4. Convertir la confirmacion en frontera real autenticada/RBAC; eliminar auto-grant como semantica productiva.
5. Crear plan de candidato con dev/inode/size/mtime_ns exactos y revalidacion descriptor-based.
6. Diseñar receipt durable de SUCCESS/PARTIAL_DELETE/FAILED con lista exacta de efectos.
7. Hacer threat tests de forge/replay/crash/audit failure/path swap.
8. Solo despues realizar una nueva revision GO/NO-GO. Ningun paso implica todavia borrar logs reales.
