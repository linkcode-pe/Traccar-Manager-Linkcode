from manager.operational_health_history import read_operational_health_history

def test_operational_history_is_bounded_read_only():
    d=read_operational_health_history(40)
    assert d["persistent"] is True and d["read_only"] is True
    assert len(d["events"])<=40
    for e in d["events"]:
        assert e["state"] in {"HEALTHY","OBSERVATION","ATTENTION","CRITICAL"}
        assert e["started_at_utc"]
