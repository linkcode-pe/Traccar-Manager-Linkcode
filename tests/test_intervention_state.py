from manager.incident_decisions import intervention_state

def test_intervention_state_none():
    assert intervention_state([])['code']=='NONE'

def test_intervention_state_progression():
    assert intervention_state([{'event_type':'AUTHORIZATION_REQUESTED'}])['code']=='PREPARED'
    assert intervention_state([{'event_type':'AUTHORIZATION_GRANTED'}])['code']=='AUTHORIZED'
    assert intervention_state([{'event_type':'EXECUTION_COMPLETED'}])['code']=='EXECUTED'

def test_intervention_failure_has_conservative_precedence():
    events=[{'event_type':'EXECUTION_COMPLETED'},{'event_type':'EXECUTION_FAILED'}]
    assert intervention_state(events)['code']=='FAILED'
