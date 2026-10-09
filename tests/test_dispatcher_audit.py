import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from worker.audit.ledger import AuditLedger, LedgerError, utc_now
from worker.dispatcher import (
    ActorContext, DashboardDispatchResult, DispatchError, Job, allowed_operations,
    create_preview, dispatch_job, record_authorization,
)
from api.dev_fixture_sources_v1 import FixtureDashboardDataSource
from api.dev_http_dashboard_v1 import FixtureReadAuthorizer
from api.read_only_dashboard_v1 import (
    ActorContext as APIActorContext, DashboardAPIError, DashboardRequestDTO,
    DispatcherAuditGateway, ReadOnlyDashboardProvider, snapshot_to_dict,
)


ROLE = "traccar.status.read"
ACTOR = ActorContext("requester-test", frozenset({ROLE}))


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class DispatcherAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.tmp.name) / "ledger.jsonl")
        self.job = Job(
            schema_version=1, job_id="job-test-1", operation="traccar.status", payload={},
            requested_by=ACTOR.subject, created_at_utc=utc_now(),
            idempotency_key="idem-test-1", request_id="request-test-1",
        )
        self.preview = create_preview(self.ledger, self.job, ACTOR)
        issued = utc_now()
        expires = stamp(datetime.now(timezone.utc) + timedelta(hours=1))
        self.auth = record_authorization(
            self.ledger, self.job, ACTOR, self.preview, authorization_id="auth-test-1",
            issued_at_utc=issued, expires_at_utc=expires,
        )
        self.job = replace(self.job, preview_id=self.preview.preview_id,
                           authorization_id=self.auth.authorization_id)

    def tearDown(self):
        self.tmp.cleanup()

    def records(self):
        path = Path(self.tmp.name) / "ledger.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def executor_result(self):
        return {
            "confirmed": True,
            "outcome": "SUCCEEDED",
            "observed_at_utc": utc_now(),
            "source": "systemd",
            "unit": "traccar.service",
            "properties": {
                "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
                "UnitFileState": "enabled", "Result": "success",
            },
        }

    def dispatch(self, executor):
        return dispatch_job(self.job, ACTOR, ledger=self.ledger, preview=self.preview,
                            authorization=self.auth, executor=executor)

    def test_preview_is_static_and_only_operation_is_allowlisted(self):
        self.assertEqual(allowed_operations(), ("dashboard.snapshot.read.v1", "traccar.status"))
        self.assertEqual(self.preview.plan["target"], {"type": "systemd-unit", "id": "traccar.service"})
        self.assertEqual(self.preview.plan["payload"], {})
        self.assertEqual(self.preview.plan["properties"],
                         ["ActiveState", "LoadState", "Result", "SubState", "UnitFileState"])
        self.assertEqual([r["event_type"] for r in self.records()], [
            "REQUEST_RECEIVED", "VALIDATION_PASSED", "PREVIEW_STARTED", "PREVIEW_COMPLETED",
            "AUTHORIZATION_REQUESTED", "AUTHORIZATION_GRANTED",
        ])

    def test_preview_and_authorization_are_idempotent_and_do_not_dispatch(self):
        before = len(self.records())
        p2 = create_preview(self.ledger, self.job, ACTOR)
        a2 = record_authorization(
            self.ledger, self.job, ACTOR, p2, authorization_id=self.auth.authorization_id,
            issued_at_utc=self.auth.issued_at_utc, expires_at_utc=self.auth.expires_at_utc,
        )
        self.assertEqual(p2.preview_hash, self.preview.preview_hash)
        self.assertEqual(a2.authorization_id, self.auth.authorization_id)
        self.assertEqual(len(self.records()), before)
        self.assertFalse(any(r["event_type"] == "EXECUTION_STARTED" for r in self.records()))

    def test_authorization_scope_and_expiry_are_checked_before_executor(self):
        spy = Mock(return_value=self.executor_result())
        bad = replace(self.auth, scope={**self.auth.scope, "operation": "other.operation"})
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                dispatch_job(self.job, ACTOR, ledger=self.ledger, preview=self.preview,
                             authorization=bad, executor=spy)
        self.assertEqual(cm.exception.code, "E303_AUTHORIZATION_SCOPE_MISMATCH")
        spy.assert_not_called()
        self.assertTrue(any(r["event_type"] == "EXECUTION_DENIED" for r in self.records()))

    def test_expired_authorization_is_denied_and_not_executed(self):
        expired = replace(self.auth, expires_at_utc=stamp(datetime.now(timezone.utc) - timedelta(seconds=1)))
        spy = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                dispatch_job(self.job, ACTOR, ledger=self.ledger, preview=self.preview,
                             authorization=expired, executor=spy)
        self.assertEqual(cm.exception.code, "E302_AUTHORIZATION_EXPIRED")
        spy.assert_not_called()

    def test_prepare_receipt_precedes_executor_and_success_is_finalized(self):
        called = []
        def executor(payload):
            self.assertEqual(payload, {})
            records = self.records()
            self.assertEqual(records[-1]["event_type"], "EXECUTION_STARTED")
            self.assertEqual(records[-1]["phase"], "AUDIT_PREPARE")
            self.assertTrue(self.ledger.verify().valid)
            called.append(True)
            return self.executor_result()
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            result = self.dispatch(executor)
        self.assertEqual(result["outcome"], "SUCCEEDED")
        self.assertEqual(called, [True])
        events = [r["event_type"] for r in self.records()]
        self.assertEqual(events[-3:], ["EXECUTION_STARTED", "EXECUTION_COMPLETED", "AUDIT_FINALIZED"])
        self.assertTrue(self.ledger.verify().valid)
        self.assertEqual(self.records()[-2]["result"]["confirmed"], True)

    def test_ledger_prepare_failure_blocks_executor(self):
        spy = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "prepare_execution", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E700_AUDIT_UNAVAILABLE")
        spy.assert_not_called()

    def test_missing_executor_is_denied_and_audited(self):
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(None)
        self.assertEqual(cm.exception.code, "E401_HELPER_NOT_AUTHORIZED")
        events = [r["event_type"] for r in self.records()]
        self.assertEqual(events[-3:], ["EXECUTION_DENIED", "JOB_REJECTED", "AUDIT_FINALIZED"])
        self.assertFalse(any(r["event_type"] == "EXECUTION_STARTED" for r in self.records()))

    def test_second_dispatch_cannot_reuse_single_use_authorization(self):
        first = Mock(return_value=self.executor_result())
        second = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            self.dispatch(first)
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(second)
        self.assertEqual(cm.exception.code, "E304_AUTHORIZATION_ALREADY_USED")
        first.assert_called_once_with({})
        second.assert_not_called()

    def test_result_audit_failure_is_not_success_and_cannot_replay(self):
        spy = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "record_result", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E701_AUDIT_WRITE_FAILED")
        spy.assert_called_once_with({})
        retry = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as retry_error:
                self.dispatch(retry)
        self.assertEqual(retry_error.exception.code, "E304_AUTHORIZATION_ALREADY_USED")
        retry.assert_not_called()

    def test_malformed_executor_output_is_audited_as_sanitized_failure(self):
        spy = Mock(return_value={"confirmed": False, "raw_exception": "must-not-be-recorded"})
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E900_INTERNAL_ERROR")
        records = self.records()
        failed = next(r for r in records if r["event_type"] == "EXECUTION_FAILED")
        self.assertEqual(failed["error_code"], "E900_INTERNAL_ERROR")
        self.assertNotIn("raw_exception", json.dumps(failed))
        self.assertEqual(records[-1]["event_type"], "AUDIT_FINALIZED")

    def test_executor_exception_is_sanitized_and_no_retry_is_possible(self):
        spy = Mock(side_effect=RuntimeError("secret raw exception detail"))
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E900_INTERNAL_ERROR")
        failed = next(r for r in self.records() if r["event_type"] == "EXECUTION_FAILED")
        self.assertNotIn("secret raw exception detail", json.dumps(failed))
        retry = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError):
                self.dispatch(retry)
        retry.assert_not_called()

    def test_root_execution_is_rejected_before_executor(self):
        spy = Mock(return_value=self.executor_result())
        with patch("worker.dispatcher.os.geteuid", return_value=0):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E402_PRIVILEGE_INSUFFICIENT")
        spy.assert_not_called()
        self.assertFalse(any(r["event_type"] == "EXECUTION_STARTED" for r in self.records()))

    def test_no_callable_real_handler_is_imported(self):
        import worker.dispatcher as dispatcher
        self.assertFalse(hasattr(dispatcher, "_traccar_status"))
        self.assertNotIn("worker.operations.traccar_status", Path(dispatcher.__file__).read_text())
        self.assertEqual(allowed_operations(), ("dashboard.snapshot.read.v1", "traccar.status"))

    def test_traccar_status_retains_its_fixed_plan_and_mock_result(self):
        self.assertEqual(self.preview.plan["operation"], "traccar.status")
        self.assertEqual(self.preview.plan["target"], {"type": "systemd-unit", "id": "traccar.service"})
        self.assertEqual(self.preview.plan["properties"],
                         ["ActiveState", "LoadState", "Result", "SubState", "UnitFileState"])
        def executor(payload):
            self.assertEqual(payload, {})
            return self.executor_result()
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            result = self.dispatch(executor)
        self.assertEqual(result["unit"], "traccar.service")
        self.assertEqual(result["source"], "systemd")
        self.assertEqual(self.records()[-1]["event_type"], "AUDIT_FINALIZED")
        self.assertTrue(self.ledger.verify().valid)


class DashboardSnapshotAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.tmp.name) / "dashboard-ledger.jsonl")
        self.actor = ActorContext("dashboard-reader-test", frozenset({"dashboard.read"}))
        self.job = self.make_job("dashboard-request-1")
        self.preview, self.authorization, self.staged_job = self.stage(self.job)

    def tearDown(self):
        self.tmp.cleanup()

    def make_job(self, request_id, job_id=None, role="dashboard.read"):
        return Job(
            schema_version=1, job_id=job_id or "dashboard-job-" + request_id,
            operation="dashboard.snapshot.read.v1", payload={},
            requested_by=self.actor.subject, created_at_utc=utc_now(),
            idempotency_key="dashboard-idem-" + request_id, request_id=request_id,
        )

    def stage(self, job, actor=None):
        actor = actor or self.actor
        preview = create_preview(self.ledger, job, actor)
        issued = utc_now()
        expires = stamp(datetime.now(timezone.utc) + timedelta(minutes=2))
        authorization = record_authorization(
            self.ledger, job, actor, preview,
            authorization_id="dashboard-auth-" + job.request_id,
            issued_at_utc=issued, expires_at_utc=expires,
        )
        staged = replace(job, preview_id=preview.preview_id,
                         authorization_id=authorization.authorization_id)
        return preview, authorization, staged

    def successful_result(self, request_id=None):
        return {
            "confirmed": True, "outcome": "SUCCEEDED", "observed_at_utc": utc_now(),
            "response": {"request_id": request_id or self.job.request_id,
                         "status": "PENDING_PROVIDER"},
        }

    def dispatch(self, executor, job=None, preview=None, authorization=None):
        return dispatch_job(
            job or self.staged_job, self.actor, ledger=self.ledger,
            preview=preview or self.preview, authorization=authorization or self.authorization,
            executor=executor,
        )

    def records(self):
        return [json.loads(line) for line in self.ledger.path.read_text().splitlines()]

    def test_dashboard_operation_is_allowlisted_with_fixed_target_and_empty_payload(self):
        self.assertIn("dashboard.snapshot.read.v1", allowed_operations())
        self.assertEqual(self.preview.plan, {
            "operation": "dashboard.snapshot.read.v1",
            "target": {"type": "dashboard", "id": "snapshot"},
            "payload": {}, "executor_port": "dashboard_snapshot",
        })
        self.assertEqual(self.actor.roles, frozenset({"dashboard.read"}))

    def test_operation_not_allowlisted_is_rejected(self):
        bad = replace(self.job, operation="dashboard.admin", request_id="bad-operation")
        with self.assertRaises(DispatchError) as cm:
            create_preview(self.ledger, bad, self.actor)
        self.assertEqual(cm.exception.code, "E100_OPERATION_NOT_ALLOWED")

    def test_insufficient_role_is_rejected_before_execution(self):
        reader_without_role = ActorContext("no-role", frozenset({"dashboard.write"}))
        job = self.make_job("dashboard-no-role")
        with self.assertRaises(DispatchError) as cm:
            create_preview(self.ledger, job, reader_without_role)
        self.assertEqual(cm.exception.code, "E104_UNAUTHORIZED_REQUESTER")

    def test_audit_prepare_precedes_executor_and_success_has_verified_receipts(self):
        called = []
        def executor(payload):
            self.assertEqual(payload, {})
            self.assertEqual(self.records()[-1]["phase"], "AUDIT_PREPARE")
            self.assertTrue(self.ledger.verify().valid)
            called.append(True)
            return self.successful_result()
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            result = self.dispatch(executor)
        self.assertIsInstance(result, DashboardDispatchResult)
        self.assertEqual(called, [True])
        self.assertEqual(len(result.receipts), 9)
        self.assertTrue(result.integrity_valid)
        self.assertTrue(all(self.ledger.verify_receipt(receipt) for receipt in result.receipts))
        self.assertEqual([row["event_type"] for row in self.records()][-3:],
                         ["EXECUTION_STARTED", "EXECUTION_COMPLETED", "AUDIT_FINALIZED"])
        self.assertTrue(self.ledger.verify().valid)

    def test_audit_prepare_failure_blocks_execution(self):
        spy = Mock(return_value=self.successful_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "prepare_execution", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy)
        self.assertEqual(cm.exception.code, "E700_AUDIT_UNAVAILABLE")
        spy.assert_not_called()

    def test_failed_result_is_audited_and_never_returned_as_success(self):
        failed = {"confirmed": True, "outcome": "FAILED", "error_code": "E500_EXECUTION_FAILED"}
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(lambda payload: failed)
        self.assertEqual(cm.exception.code, "E500_EXECUTION_FAILED")
        rows = self.records()
        self.assertEqual(rows[-2]["event_type"], "EXECUTION_FAILED")
        self.assertEqual(rows[-1]["event_type"], "AUDIT_FINALIZED")
        self.assertTrue(self.ledger.verify().valid)

    def test_finalization_failure_never_returns_success(self):
        original = self.ledger.append
        def fail_final(event):
            if event.event_type == "AUDIT_FINALIZED":
                raise LedgerError("E700_AUDIT_UNAVAILABLE")
            return original(event)
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "append", side_effect=fail_final):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(lambda payload: self.successful_result())
        self.assertEqual(cm.exception.code, "E701_AUDIT_WRITE_FAILED")
        self.assertNotEqual(self.records()[-1]["event_type"], "AUDIT_FINALIZED")

    def test_duplicate_request_id_is_rejected(self):
        duplicate = self.make_job(self.job.request_id, job_id="different-dashboard-job")
        with self.assertRaises(DispatchError) as cm:
            create_preview(self.ledger, duplicate, self.actor)
        self.assertEqual(cm.exception.code, "E800_CONCURRENCY_CONFLICT")

    def test_authorization_is_single_use(self):
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            self.dispatch(lambda payload: self.successful_result())
            second = Mock(return_value=self.successful_result())
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(second)
        self.assertEqual(cm.exception.code, "E304_AUTHORIZATION_ALREADY_USED")
        second.assert_not_called()

    def test_invalid_preview_receipt_blocks_execution(self):
        bad_receipt = replace(self.preview.receipts[0], event_hash="f" * 64)
        bad_preview = replace(self.preview, receipts=(bad_receipt,) + self.preview.receipts[1:])
        spy = Mock(return_value=self.successful_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError) as cm:
                self.dispatch(spy, preview=bad_preview)
        self.assertEqual(cm.exception.code, "E700_AUDIT_UNAVAILABLE")
        spy.assert_not_called()

    def test_corrupt_hash_chain_blocks_execution(self):
        rows = self.records()
        rows[0]["status"] = "TAMPERED"
        self.ledger.path.write_text("\\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\\n")
        self.assertFalse(self.ledger.verify().valid)
        spy = Mock(return_value=self.successful_result())
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            with self.assertRaises(DispatchError):
                self.dispatch(spy)
        spy.assert_not_called()

    def test_event_records_have_no_secrets_or_position_details(self):
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            self.dispatch(lambda payload: self.successful_result())
        encoded = json.dumps(self.records()).lower()
        for forbidden in ("password", "cookie", "token", "secret", "latitude", "longitude", "address", "uniqueid", "sql", "response"):
            self.assertNotIn(forbidden, encoded)

    def test_api_routes_read_through_dispatcher_and_fixture_only(self):
        source = FixtureDashboardDataSource()
        api_actor = APIActorContext("fixture-dashboard-reader", frozenset({"dashboard.read"}))
        api = ReadOnlyDashboardProvider(
            source, allowed_provider_ids=frozenset({source.provider_id}),
            authorizer=FixtureReadAuthorizer(),
            execution_gateway=DispatcherAuditGateway(self.ledger),
        )
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            snapshot = api.read({"request_id": "api-dashboard-fixture"}, api_actor)
        self.assertEqual(snapshot.request_id, "api-dashboard-fixture")
        self.assertTrue(self.ledger.verify().valid)
        encoded = json.dumps(self.records()).lower()
        self.assertNotIn("response", encoded)
        self.assertNotIn("latitude", encoded)
        self.assertIs(type(source), FixtureDashboardDataSource)

    def test_api_audit_prepare_failure_is_stable_and_blocks_fixture(self):
        source = FixtureDashboardDataSource()
        actor = APIActorContext("fixture-dashboard-reader", frozenset({"dashboard.read"}))
        api = ReadOnlyDashboardProvider(source, allowed_provider_ids=frozenset({source.provider_id}),
            authorizer=FixtureReadAuthorizer(),
            execution_gateway=DispatcherAuditGateway(self.ledger))
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "prepare_execution", side_effect=LedgerError("E700_AUDIT_UNAVAILABLE")):
            with self.assertRaises(DashboardAPIError) as cm:
                api.read({"request_id": "api-prepare-fail"}, actor)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.metrics_source.calls, 0)

    def test_api_finalization_failure_returns_no_snapshot(self):
        source = FixtureDashboardDataSource()
        actor = APIActorContext("fixture-dashboard-reader", frozenset({"dashboard.read"}))
        api = ReadOnlyDashboardProvider(source, allowed_provider_ids=frozenset({source.provider_id}),
            authorizer=FixtureReadAuthorizer(),
            execution_gateway=DispatcherAuditGateway(self.ledger))
        original = self.ledger.append
        def fail_final(event):
            if event.event_type == "AUDIT_FINALIZED":
                raise LedgerError("E700_AUDIT_UNAVAILABLE")
            return original(event)
        with patch("worker.dispatcher.os.geteuid", return_value=1000), \
             patch.object(self.ledger, "append", side_effect=fail_final):
            with self.assertRaises(DashboardAPIError) as cm:
                api.read({"request_id": "api-final-fail"}, actor)
        self.assertEqual(cm.exception.code, "API_AUDIT_UNAVAILABLE")
        self.assertEqual(source.metrics_source.calls, 1)

    def test_same_request_id_is_idempotent_in_facade_and_duplicate_actor_is_rejected(self):
        source = FixtureDashboardDataSource()
        actor = APIActorContext("fixture-dashboard-reader", frozenset({"dashboard.read"}))
        api = ReadOnlyDashboardProvider(source, allowed_provider_ids=frozenset({source.provider_id}),
            authorizer=FixtureReadAuthorizer(),
            execution_gateway=DispatcherAuditGateway(self.ledger))
        with patch("worker.dispatcher.os.geteuid", return_value=1000):
            first = api.read({"request_id": "api-idempotent"}, actor)
            second = api.read({"request_id": "api-idempotent"}, actor)
        self.assertEqual(first, second)
        self.assertEqual(source.metrics_source.calls, 1)
        other = APIActorContext("other-subject", frozenset({"dashboard.read"}))
        with self.assertRaises(DashboardAPIError) as cm:
            api.read({"request_id": "api-idempotent"}, other)
        self.assertEqual(cm.exception.code, "API_INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
