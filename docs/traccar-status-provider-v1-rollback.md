# Traccar status Worker candidate — rollback plan

**Planning only. No rollback or deployment action has been executed.** This is a pure, conditional plan for a future, separately authorized installation. The planner in `manager/status_rollback_plan.py` reads only its supplied manifest/inventory arguments and returns proposed actions; it has no filesystem, account, group, process, socket, or service access.

## Preconditions for a future rollback phase

1. Obtain explicit authorization for a distinct rollback phase and record its unique installation ID.
2. Preserve the verified pre-install manifest, SHA-256 values, and protected backups. Do not overwrite backups or treat a missing manifest as permission to delete.
3. Perform a read-only inventory of the candidate Worker unit, Manager drop-in, runtime directory, state directory, shared audit ledger, and candidate Worker/IPC identities. Record actual checksums and ownership without following symlinks.
4. If provenance, checksum, owner, group, active process, or dependency status is uncertain, stop and request review. Never infer that a resource belongs to this candidate from its name alone.

## Conditional actions

- Remove a candidate artifact only if the signed-off manifest says it was absent before this installation, says this installation created it, its installation ID matches, and its present identity and checksum still match. Otherwise preserve it or require manual review.
- Restore an originally present file only from its verified pre-install backup, after matching the destination identity and confirming that restoration is separately authorized. Do not replace unrelated or changed files.
- Remove a Worker account or group only when the manifest proves this installation created it and a fresh read-only check proves no process or other resource depends on it. Preserve pre-existing identities.
- Retain Worker state and the audit ledger by default. Archival, retention, or deletion of audit data requires a separate decision.
- Verify the Manager application against the pre-install health baseline using an approved read-only check. If it regressed, stop; do not restart it automatically.
- Review the proposed plan, execute only the individually authorized actions through the approved deployment channel, and record before/after hashes. The planner itself never executes the plan.

## Candidate test coverage

`tests/test_status_rollback_plan.py` tests matching-install provenance, changed checksums, verified-backup restoration, pre-existing identity preservation, dependency checks, conservative retention of audit/state data, unknown-resource rejection, and the Manager verification step. These are pure in-memory planning tests; they do not invoke the planner against the server or perform rollback.
