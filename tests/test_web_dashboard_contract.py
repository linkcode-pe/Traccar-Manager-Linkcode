import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from api.dashboard_status_contract import to_dashboard_status
from worker.audit.ledger import AuditLedger, utc_now
from worker.dispatcher import (
    ActorContext, Job, create_preview, dispatch_job, record_authorization,
)
from worker.operations import traccar_status

ROLE = "traccar.status.read"
ACTOR = ActorContext("dashboard-test", frozenset({ROLE}))


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class WebDashboardContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = AuditLedger(Path(self.temp.name) / "isolated-ledger.jsonl")
        base = Job(1, "dashboard-job", "traccar.status", {}, ACTOR.subject, utc_now(),
                   "dashboard-idem", request_id="dashboard-request")
        self.preview = create_preview(self.ledger, base, ACTOR)
        auth = record_authorization(
            self.ledger, base, ACTOR, self.preview, authorization_id="dashboard-auth",
            issued_at_utc=utc_now(),
            expires_at_utc=stamp(datetime.now(timezone.utc) + timedelta(minutes=5)),
        )
        self.job = replace(base, preview_id=self.preview.preview_id,
                           authorization_id=auth.authorization_id)
        self.auth = auth

    def tearDown(self):
        self.temp.cleanup()

    def adapter_fixture(self):
        return {
            "schema_version": 1, "operation": "traccar.status", "result": "SUCCEEDED",
            "observed_at_utc": utc_now(), "source": "systemd", "unit": "traccar.service",
            "state": {
                "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
                "UnitFileState": "enabled", "Result": "success",
            },
        }

    def test_mocked_adapter_flows_through_dispatcher_to_dashboard_contract(self):
        mocked_adapter_result = self.adapter_fixture()
        with patch.object(traccar_status, "handle", return_value=mocked_adapter_result) as adapter_mock:
            def executor(payload):
                self.assertEqual(payload, {})
                adapter = adapter_mock(payload)  # patched stub; real handler is never called
                return {
                    "confirmed": True, "outcome": "SUCCEEDED",
                    "observed_at_utc": adapter["observed_at_utc"],
                    "source": adapter["source"], "unit": adapter["unit"],
                    "properties": adapter["state"],
                }
            with patch("worker.dispatcher.os.geteuid", return_value=1000):
                dispatched = dispatch_job(self.job, ACTOR, ledger=self.ledger,
                                           preview=self.preview, authorization=self.auth,
                                           executor=executor)
            adapter_mock.assert_called_once_with({})
        model = to_dashboard_status(dispatched)
        self.assertEqual(model["status_label"], "Activo")
        self.assertEqual(model["state"]["active_state"], "active")
        self.assertEqual(model["unit"], "traccar.service")
        self.assertEqual(model["interpretation"], "systemd_unit_state_only")
        self.assertNotIn("n_restarts", model["state"])
        self.assertTrue(self.ledger.verify().valid)

    def test_contract_does_not_claim_application_health(self):
        fixture = {
            "confirmed": True, "outcome": "SUCCEEDED", "observed_at_utc": utc_now(),
            "source": "systemd", "unit": "traccar.service",
            "properties": {"LoadState": "loaded", "ActiveState": "active",
                           "SubState": "running", "UnitFileState": "enabled", "Result": "success"},
        }
        model = to_dashboard_status(fixture)
        self.assertEqual(model["interpretation"], "systemd_unit_state_only")
        self.assertNotIn("healthy", model)
        self.assertNotIn("database", model)

    def test_contract_rejects_extra_or_missing_systemd_properties(self):
        fixture = {
            "confirmed": True, "outcome": "SUCCEEDED", "observed_at_utc": utc_now(),
            "source": "systemd", "unit": "traccar.service",
            "properties": {"LoadState": "loaded", "ActiveState": "active",
                           "SubState": "running", "UnitFileState": "enabled", "Result": "success"},
        }
        for properties in [dict(fixture["properties"], ExecStart="unsafe"),
                           {k: v for k, v in fixture["properties"].items() if k != "Result"}]:
            with self.subTest(properties=properties), self.assertRaises(ValueError):
                to_dashboard_status(dict(fixture, properties=properties))

    def test_contract_rejects_unconfirmed_or_wrong_target(self):
        fixture = {
            "confirmed": True, "outcome": "SUCCEEDED", "observed_at_utc": utc_now(),
            "source": "systemd", "unit": "traccar.service",
            "properties": {"LoadState": "loaded", "ActiveState": "active",
                           "SubState": "running", "UnitFileState": "enabled", "Result": "success"},
        }
        with self.assertRaises(ValueError):
            to_dashboard_status(dict(fixture, confirmed=False))
        with self.assertRaises(ValueError):
            to_dashboard_status(dict(fixture, unit="other.service"))


if __name__ == "__main__":
    unittest.main()
