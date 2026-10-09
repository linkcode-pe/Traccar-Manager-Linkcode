"""Pure logic tests; never execute a rollback or touch the Manager runtime."""
from __future__ import annotations

import unittest

from manager.status_rollback_plan import build_candidate_rollback_plan


INSTALL_ID = "candidate-install-20261004"
OLD_HASH = "a" * 64
NEW_HASH = "b" * 64


class StatusRollbackPlanTests(unittest.TestCase):
    def test_removes_only_matching_created_artifacts_and_identities(self):
        actions = build_candidate_rollback_plan(
            install_id=INSTALL_ID,
            artifacts={
                "worker_unit": {
                    "originally_present": False, "created_by_candidate": True,
                    "install_id": INSTALL_ID, "installed_sha256": NEW_HASH,
                    "current_sha256": NEW_HASH,
                },
                "manager_dropin": {
                    "originally_present": False, "created_by_candidate": False,
                },
                "worker_state_directory": {
                    "originally_present": False, "created_by_candidate": True,
                    "install_id": INSTALL_ID, "installed_sha256": NEW_HASH,
                    "current_sha256": NEW_HASH,
                },
            },
            identities={
                "worker_user": {"created_by_candidate": True, "install_id": INSTALL_ID,
                                "has_dependents": False},
                "ipc_group": {"created_by_candidate": False},
            },
        )
        by_resource = {item.resource: item for item in actions}
        self.assertEqual("REMOVE_CREATED_ARTIFACT", by_resource["worker_unit"].action)
        self.assertEqual("PRESERVE_UNOWNED", by_resource["manager_dropin"].action)
        self.assertEqual("RETAIN_CANDIDATE_DATA", by_resource["worker_state_directory"].action)
        self.assertEqual("REMOVE_CREATED_IDENTITY", by_resource["worker_user"].action)
        self.assertEqual("PRESERVE_PREEXISTING_IDENTITY", by_resource["ipc_group"].action)
        self.assertEqual("VERIFY_MANAGER_HEALTH", actions[-1].action)

    def test_preexisting_files_are_restored_from_verified_backups_not_deleted(self):
        actions = build_candidate_rollback_plan(
            install_id=INSTALL_ID,
            artifacts={
                "manager_dropin": {
                    "originally_present": True, "created_by_candidate": False,
                    "backup_verified": True, "backup_sha256": OLD_HASH,
                    "current_sha256": NEW_HASH,
                },
                "worker_unit": {
                    "originally_present": True, "created_by_candidate": False,
                    "backup_verified": True, "backup_sha256": OLD_HASH,
                    "current_sha256": OLD_HASH,
                },
            },
            identities={},
        )
        by_resource = {item.resource: item for item in actions}
        self.assertEqual("RESTORE_PREEXISTING_BACKUP", by_resource["manager_dropin"].action)
        self.assertEqual(OLD_HASH, by_resource["manager_dropin"].backup_sha256)
        self.assertEqual("PRESERVE_PREEXISTING", by_resource["worker_unit"].action)
        self.assertNotIn("REMOVE_CREATED_ARTIFACT", {item.action for item in actions})

    def test_modified_or_unverified_created_resources_are_never_auto_removed(self):
        actions = build_candidate_rollback_plan(
            install_id=INSTALL_ID,
            artifacts={
                "worker_unit": {
                    "originally_present": False, "created_by_candidate": True,
                    "install_id": INSTALL_ID, "installed_sha256": NEW_HASH,
                    "current_sha256": OLD_HASH,
                },
            },
            identities={
                "ipc_group": {"created_by_candidate": True, "install_id": INSTALL_ID,
                               "has_dependents": True},
            },
        )
        by_resource = {item.resource: item for item in actions}
        self.assertEqual("MANUAL_REVIEW_NO_CHANGE", by_resource["worker_unit"].action)
        self.assertEqual("RETAIN_IDENTITY", by_resource["ipc_group"].action)
        self.assertNotIn("REMOVE_CREATED_ARTIFACT", {item.action for item in actions})
        self.assertNotIn("REMOVE_CREATED_IDENTITY", {item.action for item in actions})

    def test_unknown_resources_and_bad_provenance_fail_closed(self):
        with self.assertRaises(ValueError):
            build_candidate_rollback_plan(
                install_id=INSTALL_ID,
                artifacts={"arbitrary_path": {"created_by_candidate": True}},
                identities={},
            )
        with self.assertRaises(ValueError):
            build_candidate_rollback_plan(
                install_id=INSTALL_ID,
                artifacts={"worker_unit": {"originally_present": 1,
                                            "created_by_candidate": True}},
                identities={},
            )


if __name__ == "__main__":
    unittest.main()
