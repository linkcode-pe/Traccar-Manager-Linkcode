from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from worker.audit.ledger import (
    AuditLedger, LedgerError, LedgerEvent, _calculate_event_hash, canonical_json,
    validate_event,
)

ACTOR = {"subject_id": "requester-test", "actor_type": "human"}
APPROVER = {"subject_id": "rbac-test", "actor_type": "policy"}
TARGET = {"type": "systemd-unit", "id": "traccar.service"}
PARAMS = "a" * 64
PREVIEW_HASH = "b" * 64
SCOPE_HASH = "c" * 64


def event(event_type, phase, *, actor=ACTOR, request_id="req-1", job_id="job-1",
          operation="traccar.status", requester=ACTOR, parameters_hash=PARAMS,
          target=TARGET, **kwargs):
    return LedgerEvent.create(
        event_type=event_type, phase=phase, request_id=request_id, job_id=job_id,
        operation=operation, actor=actor, requester=requester,
        parameters_hash=parameters_hash, target=target, **kwargs,
    )


def auth_record(decision, *, issued=None, expiration=None, approval_mode="RBAC_READ"):
    issued = issued or datetime.now(timezone.utc) - timedelta(seconds=1)
    expiration = expiration or datetime.now(timezone.utc) + timedelta(hours=1)
    stamp = issued.isoformat(timespec="microseconds").replace("+00:00", "Z")
    expiry = expiration.isoformat(timespec="microseconds").replace("+00:00", "Z")
    scope = {"operation": "traccar.status", "target": TARGET,
             "parameters_hash": PARAMS, "preview_hash": PREVIEW_HASH}
    return {
        "authorization_id": "auth-1", "requester": ACTOR, "approver": APPROVER,
        "operation": "traccar.status", "target": TARGET, "preview_id": "preview-1",
        "preview_hash": PREVIEW_HASH, "timestamp": stamp, "expiration": expiry,
        "authorization_scope": scope, "parameters_hash": PARAMS,
        "one_time_nonce": "nonce-test-1", "decision": decision,
        "approval_mode": approval_mode,
    }


class AuditLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"
        self.ledger = AuditLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def req(self, **kwargs):
        return event("REQUEST_RECEIVED", "REQUEST", **kwargs)

    def append_request_and_validation(self):
        first = self.req()
        self.ledger.append(first)
        valid = event("VALIDATION_PASSED", "VALIDATION")
        self.ledger.append(valid)
        return first, valid

    def append_to_preview(self):
        self.append_request_and_validation()
        self.ledger.append(event("PREVIEW_STARTED", "PREVIEW"))
        preview = event("PREVIEW_COMPLETED", "PREVIEW", preview_id="preview-1",
                        preview_hash=PREVIEW_HASH, authorization_scope_hash=SCOPE_HASH,
                        status="COMPLETED", metadata={"plan": "static-status-query"})
        self.ledger.append(preview)
        return preview

    def append_to_auth_request(self):
        self.append_to_preview()
        pending = auth_record("PENDING")
        auth_req = event("AUTHORIZATION_REQUESTED", "AUTHORIZATION", actor=ACTOR,
                         approver=APPROVER, authorization=pending,
                         authorization_id="auth-1", preview_id="preview-1",
                         preview_hash=PREVIEW_HASH,
                         authorization_scope=pending["authorization_scope"],
                         authorization_scope_hash=SCOPE_HASH, status="REQUESTED")
        self.ledger.append_authorization(auth_req)
        return pending

    def append_grant(self):
        pending = self.append_to_auth_request()
        granted = dict(pending, decision="GRANTED")
        grant = event("AUTHORIZATION_GRANTED", "AUTHORIZATION", actor=APPROVER,
                      approver=APPROVER, authorization=granted,
                      authorization_id="auth-1", preview_id="preview-1",
                      preview_hash=PREVIEW_HASH,
                      authorization_scope=granted["authorization_scope"],
                      authorization_scope_hash=SCOPE_HASH, status="GRANTED")
        self.ledger.append_authorization(grant)
        return grant

    def exec_start(self):
        return event("EXECUTION_STARTED", "AUDIT_PREPARE",
                     actor={"subject_id": "worker-test", "actor_type": "service"},
                     worker_identity="worker-test", authorization_id="auth-1",
                     preview_id="preview-1", preview_hash=PREVIEW_HASH,
                     authorization_scope_hash=SCOPE_HASH, status="STARTED")

    def test_01_valid_event(self):
        validate_event(self.req())

    def test_02_invalid_event(self):
        with self.assertRaises(LedgerError) as cm:
            validate_event(replace(self.req(), operation="not valid"))
        self.assertEqual(cm.exception.code, "E101_INVALID_OPERATION")

    def test_03_missing_required_fields(self):
        with self.assertRaises(LedgerError) as cm:
            validate_event(replace(self.req(), request_id=""))
        self.assertEqual(cm.exception.code, "E103_INVALID_PARAMETERS")

    def test_04_first_event_has_deterministic_genesis(self):
        receipt = self.ledger.append(self.req())
        stored = json.loads(self.path.read_text().splitlines()[0])
        self.assertEqual(receipt.ledger_sequence, 1)
        self.assertIsNone(stored["previous_event_id"])
        self.assertIsNone(stored["previous_event_hash"])
        self.assertIsNone(stored["previous_hash"])
        self.assertEqual(len(stored["event_hash"]), 64)

    def test_05_hash_chaining(self):
        first = self.ledger.append(self.req())
        second_event = event("VALIDATION_PASSED", "VALIDATION")
        second = self.ledger.append(second_event)
        records = [json.loads(x) for x in self.path.read_text().splitlines()]
        self.assertEqual(second.ledger_sequence, 2)
        self.assertEqual(records[1]["previous_event_id"], first.event_id)
        self.assertEqual(records[1]["previous_hash"], first.event_hash)
        self.assertEqual(second.previous_event_hash, first.event_hash)

    def test_06_valid_chain_verifies(self):
        self.append_request_and_validation()
        self.assertTrue(self.ledger.verify().valid)

    def test_07_detects_altered_event(self):
        self.ledger.append(self.req())
        lines = self.path.read_text().splitlines()
        record = json.loads(lines[0]); record["status"] = "ALTERED"
        self.path.write_text(canonical_json(record).decode() + "\n")
        report = self.ledger.verify()
        self.assertFalse(report.valid)
        self.assertEqual(report.error_code, "E702_AUDIT_INTEGRITY_FAILURE")

    def test_08_detects_incorrect_hash(self):
        self.ledger.append(self.req())
        record = json.loads(self.path.read_text().splitlines()[0]); record["event_hash"] = "f" * 64
        self.path.write_text(canonical_json(record).decode() + "\n")
        self.assertFalse(self.ledger.verify().valid)

    def test_09_detects_chain_break_even_with_recomputed_hash(self):
        self.ledger.append(self.req())
        self.ledger.append(event("VALIDATION_PASSED", "VALIDATION"))
        records = [json.loads(x) for x in self.path.read_text().splitlines()]
        records[1]["previous_event_id"] = str(uuid4())
        records[1]["event_hash"] = _calculate_event_hash(records[1])
        self.path.write_bytes(b"".join(canonical_json(r) + b"\n" for r in records))
        self.assertFalse(self.ledger.verify().valid)

    def test_10_append_success_returns_durable_receipt(self):
        receipt = self.ledger.append(self.req())
        self.assertTrue(receipt.durable)
        self.assertEqual(receipt.event_id, json.loads(self.path.read_text().splitlines()[0])["event_id"])

    def test_11_append_failure_fails_closed(self):
        unavailable = AuditLedger(Path(self.tmp.name) / "missing-parent" / "ledger.jsonl")
        with self.assertRaises(LedgerError) as cm:
            unavailable.append(self.req())
        self.assertEqual(cm.exception.code, "E700_AUDIT_UNAVAILABLE")
        self.assertFalse((Path(self.tmp.name) / "missing-parent").exists())

    def test_12_receipt_verifies(self):
        receipt = self.ledger.append(self.req())
        self.assertTrue(self.ledger.verify_receipt(receipt))

    def test_13_invalid_receipt_is_rejected(self):
        receipt = self.ledger.append(self.req())
        self.assertFalse(self.ledger.verify_receipt(replace(receipt, event_hash="0" * 64)))

    def test_14_valid_phase_transitions(self):
        self.append_to_preview()
        self.assertTrue(self.ledger.verify().valid)

    def test_15_invalid_phase_transition_is_rejected(self):
        self.ledger.append(self.req())
        with self.assertRaises(LedgerError) as cm:
            self.ledger.append(event("PREVIEW_STARTED", "PREVIEW"))
        self.assertEqual(cm.exception.code, "E802_JOB_STATE_INVALID")

    def test_16_authorization_is_separate_from_preview_and_execution(self):
        self.append_to_preview()
        with self.assertRaises(LedgerError) as cm:
            self.ledger.prepare_execution(self.exec_start())
        self.assertEqual(cm.exception.code, "E802_JOB_STATE_INVALID")
        self.assertEqual(self.ledger.verify().event_count, 4)

    def test_17_authorization_denied_cannot_execute(self):
        pending = self.append_to_auth_request()
        denied = dict(pending, decision="DENIED")
        ev = event("AUTHORIZATION_DENIED", "AUTHORIZATION", actor=APPROVER,
                   approver=APPROVER, authorization=denied, authorization_id="auth-1",
                   preview_id="preview-1", preview_hash=PREVIEW_HASH,
                   authorization_scope=denied["authorization_scope"],
                   authorization_scope_hash=SCOPE_HASH, status="DENIED",
                   error_code="E300_AUTHORIZATION_REQUIRED")
        self.ledger.append_authorization(ev)
        self.ledger.append(event("JOB_REJECTED", "AUTHORIZATION", status="REJECTED"))
        self.assertFalse(any(json.loads(x)["event_type"] == "EXECUTION_STARTED" for x in self.path.read_text().splitlines()))

    def test_18_expired_authorization_is_rejected(self):
        issued = datetime.now(timezone.utc) - timedelta(seconds=30)
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        pending = auth_record("PENDING", issued=issued, expiration=expired)
        self.append_to_preview()
        req = event("AUTHORIZATION_REQUESTED", "AUTHORIZATION", actor=ACTOR,
                    approver=APPROVER, authorization=pending, authorization_id="auth-1",
                    preview_id="preview-1", preview_hash=PREVIEW_HASH,
                    authorization_scope=pending["authorization_scope"],
                    authorization_scope_hash=SCOPE_HASH, status="REQUESTED")
        self.ledger.append_authorization(req)
        granted = dict(pending, decision="GRANTED")
        ev = event("AUTHORIZATION_GRANTED", "AUTHORIZATION", actor=APPROVER,
                   approver=APPROVER, authorization=granted, authorization_id="auth-1",
                   preview_id="preview-1", preview_hash=PREVIEW_HASH,
                   authorization_scope=granted["authorization_scope"],
                   authorization_scope_hash=SCOPE_HASH, status="GRANTED")
        with self.assertRaises(LedgerError) as cm:
            self.ledger.append_authorization(ev)
        self.assertEqual(cm.exception.code, "E302_AUTHORIZATION_EXPIRED")

    def test_19_fail_closed_no_receipt_means_no_go(self):
        unavailable = AuditLedger(Path(self.tmp.name) / "absent" / "ledger.jsonl")
        with self.assertRaises(LedgerError) as cm:
            unavailable.prepare_execution(self.exec_start())
        self.assertEqual(cm.exception.code, "E700_AUDIT_UNAVAILABLE")

    def test_20_idempotent_request_and_event_retry(self):
        original = self.req()
        first = self.ledger.append(original)
        same_event_retry = self.ledger.append(original)
        self.assertEqual(first, same_event_retry)
        duplicate_request = replace(original, event_id=str(uuid4()), timestamp="2026-09-29T14:00:00Z")
        self.assertEqual(first, self.ledger.append(duplicate_request))
        self.assertEqual(self.ledger.verify().event_count, 1)

    def test_21_event_id_duplicate_with_different_content_conflicts(self):
        original = self.req()
        self.ledger.append(original)
        conflicting = replace(event("REQUEST_RECEIVED", "REQUEST", request_id="req-2", job_id="job-2"), event_id=original.event_id)
        with self.assertRaises(LedgerError) as cm:
            self.ledger.append(conflicting)
        self.assertEqual(cm.exception.code, "E800_CONCURRENCY_CONFLICT")

    def test_22_request_id_duplicate_with_different_request_conflicts(self):
        self.ledger.append(self.req())
        conflicting = self.req(job_id="job-other", operation="traccar.status")
        with self.assertRaises(LedgerError) as cm:
            self.ledger.append(conflicting)
        self.assertEqual(cm.exception.code, "E800_CONCURRENCY_CONFLICT")

    def test_authorization_consumption_is_one_time(self):
        self.append_grant()
        self.ledger.prepare_execution(self.exec_start())
        repeated = replace(self.exec_start(), event_id=str(uuid4()))
        with self.assertRaises(LedgerError) as cm:
            self.ledger.prepare_execution(repeated)
        self.assertEqual(cm.exception.code, "E304_AUTHORIZATION_ALREADY_USED")

    def test_result_requires_confirmed_result(self):
        self.append_grant()
        self.ledger.prepare_execution(self.exec_start())
        bad = event("EXECUTION_COMPLETED", "AUDIT_RESULT",
                    actor={"subject_id": "worker-test", "actor_type": "service"},
                    worker_identity="worker-test", authorization_id="auth-1",
                    preview_id="preview-1", preview_hash=PREVIEW_HASH,
                    result={"confirmed": False}, status="COMPLETED")
        with self.assertRaises(LedgerError) as cm:
            self.ledger.record_result(bad)
        self.assertEqual(cm.exception.code, "E500_EXECUTION_FAILED")

    def test_successful_flow_finalizes_without_running_operation(self):
        self.append_grant()
        self.ledger.prepare_execution(self.exec_start())
        result = event("EXECUTION_COMPLETED", "AUDIT_RESULT",
                       actor={"subject_id": "worker-test", "actor_type": "service"},
                       worker_identity="worker-test", authorization_id="auth-1",
                       preview_id="preview-1", preview_hash=PREVIEW_HASH,
                       result={"confirmed": True, "outcome": "SUCCEEDED"},
                       result_code="SUCCEEDED", status="COMPLETED")
        self.ledger.record_result(result)
        finalized = event("AUDIT_FINALIZED", "AUDIT_FINALIZATION",
                          actor={"subject_id": "audit-ledger-test", "actor_type": "service"},
                          status="FINALIZED")
        self.ledger.append(finalized)
        self.assertTrue(self.ledger.verify().valid)


    def test_shared_read_only_view_verifies_and_cannot_append(self):
        state = Path(self.tmp.name) / "worker-state"
        state.mkdir(mode=0o750)
        os.chmod(state, 0o750)
        path = state / "audit.jsonl"
        writer = AuditLedger(
            path, create_mode=0o640, expected_owner_uid=os.geteuid(),
            expected_group_gid=os.getegid(), expected_file_mode=0o640,
            expected_directory_uid=os.geteuid(), expected_directory_gid=os.getegid(),
            expected_directory_mode=0o750,
        )
        receipt = writer.append(self.req(request_id="shared-read-01", job_id="shared-job-01"))
        reader = AuditLedger(
            path, expected_owner_uid=os.geteuid(), expected_group_gid=os.getegid(),
            expected_file_mode=0o640, expected_directory_uid=os.geteuid(),
            expected_directory_gid=os.getegid(), expected_directory_mode=0o750,
            read_only=True,
        )
        before = path.read_bytes()
        self.assertTrue(reader.verify().valid)
        self.assertTrue(reader.verify_receipt(receipt))
        with self.assertRaises(LedgerError) as cm:
            reader.append(None)
        self.assertEqual("E700_AUDIT_UNAVAILABLE", cm.exception.code)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0o640, path.stat().st_mode & 0o777)

    def test_mode_owner_group_and_directory_policy_mismatches_fail_closed(self):
        state = Path(self.tmp.name) / "policy-state"
        state.mkdir(mode=0o750)
        os.chmod(state, 0o750)
        path = state / "audit.jsonl"
        writer = AuditLedger(
            path, create_mode=0o640, expected_owner_uid=os.geteuid(),
            expected_group_gid=os.getegid(), expected_file_mode=0o640,
            expected_directory_uid=os.geteuid(), expected_directory_gid=os.getegid(),
            expected_directory_mode=0o750,
        )
        writer.append(self.req(request_id="policy-01", job_id="policy-job-01"))
        mismatch_policies = (
            {"expected_file_mode": 0o600},
            {"expected_owner_uid": os.geteuid() + 1},
            {"expected_group_gid": os.getegid() + 1},
            {"expected_directory_uid": os.geteuid() + 1},
            {"expected_directory_gid": os.getegid() + 1},
            {"expected_directory_mode": 0o700},
        )
        for policy in mismatch_policies:
            with self.subTest(policy=policy):
                verifier = AuditLedger(path, **policy, read_only=True)
                self.assertFalse(verifier.verify().valid)

    def test_fsync_covers_initial_directory_entry_and_appended_event(self):
        from unittest.mock import patch
        with patch("worker.audit.ledger.os.fsync", wraps=os.fsync) as sync:
            self.ledger.append(self.req())
        self.assertGreaterEqual(sync.call_count, 2)
        self.assertTrue(self.ledger.verify().valid)

    def test_restart_with_new_ledger_object_continues_verified_chain(self):
        request = self.req(request_id="restart-01", job_id="restart-job-01")
        self.ledger.append(request)
        restarted = AuditLedger(self.path)
        self.assertTrue(restarted.verify().valid)
        restarted.append(event("VALIDATION_PASSED", "VALIDATION",
                               request_id="restart-01", job_id="restart-job-01"))
        self.assertEqual(2, self.ledger.verify().event_count)
        self.assertTrue(restarted.verify().valid)

    def test_concurrent_writers_keep_a_single_valid_hash_chain(self):
        def append_request(index):
            return self.ledger.append(self.req(
                request_id=f"concurrent-{index}", job_id=f"concurrent-job-{index}",
            ))
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(append_request, range(16)))
        self.assertEqual(16, len(receipts))
        report = self.ledger.verify()
        self.assertTrue(report.valid)
        self.assertEqual(16, report.event_count)
        sequences = sorted(receipt.ledger_sequence for receipt in receipts)
        self.assertEqual(list(range(1, 17)), sequences)

    def test_symlink_and_hardlink_ledgers_are_rejected(self):
        self.ledger.append(self.req())
        symlink = Path(self.tmp.name) / "symlink.jsonl"
        symlink.symlink_to(self.path)
        self.assertFalse(AuditLedger(symlink).verify().valid)
        hardlink = Path(self.tmp.name) / "hardlink.jsonl"
        os.link(self.path, hardlink)
        self.assertFalse(AuditLedger(hardlink).verify().valid)

    def test_corrupted_shared_ledger_fails_closed_for_reader_and_writer(self):
        self.ledger.append(self.req())
        record = json.loads(self.path.read_text().splitlines()[0])
        record["status"] = "TAMPERED"
        self.path.write_text(canonical_json(record).decode() + "\n")
        reader = AuditLedger(self.path, read_only=True)
        self.assertFalse(reader.verify().valid)
        with self.assertRaises(LedgerError) as cm:
            self.ledger.append(event("VALIDATION_PASSED", "VALIDATION"))
        self.assertEqual("E702_AUDIT_INTEGRITY_FAILURE", cm.exception.code)


if __name__ == "__main__":
    unittest.main()
