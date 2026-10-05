"""Pure schema and mapping tests for the fixed status protocol adapters."""
from __future__ import annotations

import unittest

from api.providers.traccar_status_protocol_v1 import (
    general_status_to_dispatcher_result,
    handler_result_to_record,
    protocol_properties_to_record,
    record_to_general_status,
)
from api.read_only_dashboard_v1 import Availability

OBSERVED = "2026-10-04T09:00:00Z"
PROPERTIES = {
    "LoadState": "loaded",
    "ActiveState": "active",
    "SubState": "running",
    "UnitFileState": "enabled",
    "Result": "success",
}
HANDLER = {
    "schema_version": 1,
    "operation": "traccar.status",
    "result": "SUCCEEDED",
    "observed_at_utc": OBSERVED,
    "source": "systemd",
    "unit": "traccar.service",
    "state": PROPERTIES,
}


class TraccarStatusProtocolAdapterTests(unittest.TestCase):
    def test_handler_schema_maps_to_fixed_status_record(self):
        record = handler_result_to_record(HANDLER)
        self.assertEqual("loaded", record.load_state)
        self.assertEqual("active", record.active_state)
        self.assertEqual("running", record.sub_state)
        self.assertEqual("enabled", record.unit_file_state)
        self.assertEqual("success", record.result)
        self.assertEqual(OBSERVED, record.observed_at_utc)

    def test_protocol_properties_map_to_record_and_dto_without_inference(self):
        record = protocol_properties_to_record(PROPERTIES, OBSERVED)
        status = record_to_general_status(record)
        self.assertEqual("active", status.traccar_service.state.value)
        self.assertEqual("running", status.traccar_service.substate.value)
        self.assertEqual("loaded", status.traccar_service.load_state.value)
        self.assertEqual("enabled", status.traccar_service.unit_file_state.value)
        self.assertEqual("success", status.traccar_service.result.value)
        for value in (status.uptime_seconds, status.version, status.overall_state):
            self.assertIs(value.availability, Availability.PENDING_PROVIDER)

    def test_dispatcher_result_contains_only_confirmed_allowlisted_fields(self):
        result = general_status_to_dispatcher_result(record_to_general_status(
            protocol_properties_to_record(PROPERTIES, OBSERVED),
        ))
        self.assertEqual({
            "confirmed", "outcome", "observed_at_utc", "source", "unit", "properties",
        }, set(result))
        self.assertIs(result["confirmed"], True)
        self.assertEqual("SUCCEEDED", result["outcome"])
        self.assertEqual("systemd", result["source"])
        self.assertEqual("traccar.service", result["unit"])
        self.assertEqual(PROPERTIES, result["properties"])

    def test_invalid_handler_schema_and_field_values_are_rejected(self):
        bad_values = (
            {key: value for key, value in HANDLER.items() if key != "state"},
            dict(HANDLER, extra="rejected"),
            dict(HANDLER, schema_version=True),
            dict(HANDLER, unit="other.service"),
            dict(HANDLER, state=dict(PROPERTIES, ActiveState="active\nforged")),
            dict(HANDLER, observed_at_utc="not-a-time"),
        )
        for bad in bad_values:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                handler_result_to_record(bad)

    def test_invalid_protocol_property_schema_and_timestamps_are_rejected(self):
        for properties, stamp in (
            ({key: value for key, value in PROPERTIES.items() if key != "Result"}, OBSERVED),
            (dict(PROPERTIES, Provider="other"), OBSERVED),
            (dict(PROPERTIES, ActiveState=[]), OBSERVED),
            (PROPERTIES, "2026-10-04T09:00:00+00:00"),
        ):
            with self.subTest(properties=properties, stamp=stamp), self.assertRaises(ValueError):
                protocol_properties_to_record(properties, stamp)

    def test_dispatcher_rejects_pending_or_mismatched_dto_values(self):
        status = record_to_general_status(protocol_properties_to_record(PROPERTIES, OBSERVED))
        bad = status.__class__(
            traccar_service=status.traccar_service,
            uptime_seconds=status.uptime_seconds,
            version=status.version,
            overall_state=status.overall_state,
            observed_at_utc="2026-10-04T10:00:00Z",
        )
        with self.assertRaises(ValueError):
            general_status_to_dispatcher_result(bad)


if __name__ == "__main__":
    unittest.main()
