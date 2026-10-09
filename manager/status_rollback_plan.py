"""Pure rollback planner for a future, separately authorized Worker install.

This module deliberately performs no file, account, group, process, or service
operations. It converts a verified install manifest and read-only inspection
results into conditional actions for a human-reviewed rollback procedure.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

_RESOURCE_KEYS = frozenset({
    "worker_unit", "manager_dropin", "runtime_directory",
    "worker_state_directory", "shared_audit_ledger",
})
_IDENTITY_KEYS = frozenset({"worker_user", "worker_group", "ipc_group"})
_DATA_KEYS = frozenset({"worker_state_directory", "shared_audit_ledger"})
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RollbackAction:
    action: str
    resource: str
    condition: str
    backup_sha256: str | None = None


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH_RE.fullmatch(value))


def _validate_inventory(value: Any, allowed: frozenset[str]) -> Mapping[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping) or not set(value).issubset(allowed):
        raise ValueError("invalid rollback inventory")
    for key, row in value.items():
        if not isinstance(key, str) or not isinstance(row, Mapping):
            raise ValueError("invalid rollback inventory")
    return value


def build_candidate_rollback_plan(*, install_id: str, artifacts: Mapping[str, Any],
                                  identities: Mapping[str, Any]) -> tuple[RollbackAction, ...]:
    """Return conditions only; never carry out a rollback or health check."""
    if not isinstance(install_id, str) or not install_id.strip() or len(install_id) > 128:
        raise ValueError("invalid install identifier")
    artifact_rows = _validate_inventory(artifacts, _RESOURCE_KEYS)
    identity_rows = _validate_inventory(identities, _IDENTITY_KEYS)
    actions: list[RollbackAction] = []

    for key in sorted(artifact_rows):
        row = artifact_rows[key]
        originally_present = row.get("originally_present")
        created = row.get("created_by_candidate")
        if type(originally_present) is not bool or type(created) is not bool:
            raise ValueError("invalid artifact provenance")
        current_hash = row.get("current_sha256")
        if current_hash is not None and not _valid_hash(current_hash):
            raise ValueError("invalid current artifact checksum")
        if originally_present:
            backup_hash = row.get("backup_sha256")
            backup_verified = row.get("backup_verified")
            if type(backup_verified) is not bool:
                raise ValueError("invalid backup status")
            if backup_verified and not _valid_hash(backup_hash):
                raise ValueError("invalid backup checksum")
            if backup_verified and current_hash != backup_hash:
                actions.append(RollbackAction(
                    "RESTORE_PREEXISTING_BACKUP", key,
                    "separately authorized; verified backup and target identity rechecked",
                    backup_hash,
                ))
            elif not backup_verified:
                actions.append(RollbackAction(
                    "MANUAL_REVIEW_NO_CHANGE", key,
                    "pre-existing content lacks a verified backup",
                ))
            else:
                actions.append(RollbackAction("PRESERVE_PREEXISTING", key, "no change needed"))
            continue

        if not created:
            actions.append(RollbackAction("PRESERVE_UNOWNED", key, "not recorded as created by this install"))
            continue
        if row.get("install_id") != install_id or not _valid_hash(row.get("installed_sha256")):
            actions.append(RollbackAction(
                "MANUAL_REVIEW_NO_CHANGE", key,
                "creation provenance or installed checksum does not match this install",
            ))
            continue
        if current_hash != row.get("installed_sha256"):
            actions.append(RollbackAction(
                "MANUAL_REVIEW_NO_CHANGE", key,
                "current content differs from the install-recorded checksum",
            ))
            continue
        if key in _DATA_KEYS:
            actions.append(RollbackAction(
                "RETAIN_CANDIDATE_DATA", key,
                "preserve audit/state data pending a separate retention decision",
            ))
        else:
            actions.append(RollbackAction(
                "REMOVE_CREATED_ARTIFACT", key,
                "separately authorized; path, install marker, and checksum rechecked",
            ))

    for key in sorted(identity_rows):
        row = identity_rows[key]
        created = row.get("created_by_candidate")
        if type(created) is not bool:
            raise ValueError("invalid identity provenance")
        if not created:
            actions.append(RollbackAction("PRESERVE_PREEXISTING_IDENTITY", key, "not created by this install"))
        elif row.get("install_id") != install_id:
            actions.append(RollbackAction(
                "MANUAL_REVIEW_NO_CHANGE", key,
                "identity creation provenance does not match this install",
            ))
        elif row.get("has_dependents") is not False:
            actions.append(RollbackAction(
                "RETAIN_IDENTITY", key,
                "remove only after a separate check proves no dependent process or resource",
            ))
        else:
            actions.append(RollbackAction(
                "REMOVE_CREATED_IDENTITY", key,
                "separately authorized; provenance and absence of dependents rechecked",
            ))

    actions.append(RollbackAction(
        "VERIFY_MANAGER_HEALTH", "manager_application",
        "read-only check against the pre-install baseline; stop on any regression",
    ))
    return tuple(actions)
