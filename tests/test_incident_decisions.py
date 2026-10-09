from manager.incident_decisions import read_incident_decisions

def test_current_incident_has_no_guessed_decisions():
    d=read_incident_decisions('component_growth-20261007T041649Z')
    assert d['linked_by']=='incident_id'
    assert d['read_only'] is True
    assert d['events']==[]

def test_invalid_incident_id_returns_empty():
    assert read_incident_decisions('')['count']==0
