from manager.incident_history import read_incidents

def test_incident_store_is_bounded_and_read_only_contract():
    data=read_incidents(30)
    assert data["persistent"] is True
    assert data["read_only"] is True
    assert len(data["events"]) <= 30
    for event in data["events"]:
        assert event["status"] in {"OPEN","RESOLVED"}
        assert event["severity"] in {"WARNING","CRITICAL"}
        assert event["id"]
