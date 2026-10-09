# Traccar status provider v1 — candidate-only implementation

**State: source candidate only. `PROVIDER_STATUS=PENDING_PROVIDER`.** This document does not authorize deployment, activation, account/group creation, runtime-directory creation, socket creation, or any service action. No real status query is performed by the test suite.

## Scope and boundary

The candidate has a fixed read-only Worker operation for the five allowlisted properties `LoadState`, `ActiveState`, `SubState`, `UnitFileState`, and `Result`. It accepts one correlated `request_id`; the request carries a protocol version, the fixed operation name, the authenticated subject, the single required role, and an empty payload. Extra fields, duplicate JSON keys, a different role, and a different protocol version fail closed.

The intended path is:

```text
Manager HTTP (loopback AF_INET)
  -> authenticated dashboard.read + traccar.status.read gate
  -> local Unix socket (fixed operation and empty payload)
  -> dedicated non-root Worker
  -> fixed handler adapter (mocked in tests; never run during this phase)
  -> Worker-owned shared hash-chain ledger, fsync before success
  -> finalization receipt over the same nine-event success chain
  -> Web read-only ledger view verifies receipt before returning status
```

The Web client validates socket path metadata and Worker peer credentials; the Worker validates the connecting Web UID and primary GID. The candidate Manager drop-in permits both `AF_INET` (existing Web listener) and `AF_UNIX` (local IPC). The Worker unit remains `AF_UNIX` only. Neither configuration has been installed or applied. Future IPC group membership is a separate, explicitly authorized deployment step; this candidate did not create any user or group.

The Worker is the sole writer to `/var/lib/traccar-manager-worker/audit.jsonl`. The intended persistent directory is mode `0750`; the ledger file is mode `0640`, owned by the Worker and its primary group. The Manager Web process has only the read access needed for receipt verification. File and directory type, owner, group, mode, link count, and no-follow checks fail closed. Appends use exclusive `flock`, a hash chain, and `fsync`; creation also syncs the containing directory. This is **not WORM** and does not protect against a privileged administrator rewriting the file. No live ownership/group access proof is claimed because the production identities and directory do not exist in this phase.

The unprivileged dashboard path without `traccar.status.read` does not contact the socket or inspect the shared ledger; its status fields remain `PENDING_PROVIDER`. A role-authorized response is not exposed unless its Worker finalization receipt verifies against the shared ledger. A missing/corrupt ledger, malformed response, or audit failure returns no successful snapshot.

## Fixed operation and safety

The operation handler is constrained in source to `/usr/bin/systemctl show --no-pager --property=LoadState,ActiveState,SubState,UnitFileState,Result traccar.service`, `shell=False`, a five-second timeout, a minimal environment, and sanitized failures. **This command was never executed during implementation, tests, or verification.** Tests replace the handler and mock the exact subprocess boundary; the full test run also uses a process guard that rejects any attempt to execute a system manager command.

No MySQL, Traccar database, Traccar API, shell-based unit control, restart, or write operation is part of this provider. No API or Worker runtime was installed or activated. The current required provider status remains `PENDING_PROVIDER`.

## Candidate validation

Validation must use a temporary copy of the checkout, a non-root test identity, an isolated network namespace with loopback only if local HTTP tests require it, and only temporary UDS paths. The mock-only focused tests cover strict protocol validation, peer-credential checks, exact command arguments without execution, one shared audit chain, read-only Web receipt verification, tampered receipts, adapter conversion, ledger policy/integrity/concurrency, and pure rollback-plan logic. The existing full suite also includes isolated temporary SQLite fixtures and fake MySQL connector objects; the temporary test environment supplies a no-connect MySQL import stub that raises if an unmocked connection is attempted. No database service is contacted. The full suite must also pass before any `CANDIDATE_VALIDATED=YES` is claimed. Test result counts and exact commands belong in the handoff report.

## Deployment remains out of scope

Do not install or apply either candidate systemd file, create the Worker account/group or IPC group, create production directories/socket, run daemon reload, query a live Manager health endpoint, or start/restart a service under this phase. Deployment requires a new explicit phase authorization, a separate review of the intended identities and primary GIDs, proof of read-only shared-ledger access, and confirmation that Manager AF_INET remains available. A passing candidate suite does not constitute production compatibility or a production test.
