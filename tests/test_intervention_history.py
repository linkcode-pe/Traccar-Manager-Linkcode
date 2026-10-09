from manager.incident_decisions import intervention_history


def ev(event_type, auth=None, request=None, job=None):
    return {
        "event_type": event_type,
        "timestamp": "2026-10-07T10:00:00Z",
        "authorization_id": auth,
        "request_id": request,
        "job_id": job,
        "operation": "maintenance.logs",
    }


def test_history_separates_authorizations():
    history = intervention_history([
        ev("AUTHORIZATION_GRANTED", auth="a1"),
        ev("EXECUTION_COMPLETED", auth="a1"),
        ev("AUTHORIZATION_GRANTED", auth="a2"),
    ])

    assert len(history) == 2
    assert history[0]["authorization_id"] == "a2"
    assert history[1]["authorization_id"] == "a1"
    assert history[1]["state"]["code"] == "EXECUTED"


def test_history_fallback_job_then_request():
    history = intervention_history([
        ev("EXECUTION_STARTED", job="j1"),
        ev("EXECUTION_FAILED", job="j1"),
        ev("AUTHORIZATION_REQUESTED", request="r2"),
    ])

    assert len(history) == 2
    assert {x["intervention_key"] for x in history} == {
        "job:j1",
        "request:r2",
    }


def test_history_unkeyed_events_are_isolated():
    history = intervention_history([
        ev("AUDIT_FINALIZED"),
        ev("AUDIT_FINALIZED"),
    ])

    assert len(history) == 2
    assert history[0]["intervention_key"] != history[1]["intervention_key"]
