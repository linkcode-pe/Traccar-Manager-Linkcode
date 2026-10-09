from manager.incident_decisions import intervention_cycle

def statuses(events):
    return [x['status'] for x in intervention_cycle(events)]

def test_cycle_empty_is_all_pending():
    assert statuses([])==['PENDING']*4

def test_cycle_authorization_evidence_does_not_invent_execution_or_audit():
    assert statuses([{'event_type':'AUTHORIZATION_GRANTED'}])==['COMPLETED','COMPLETED','PENDING','PENDING']

def test_cycle_execution_completed_without_finalization_keeps_audit_pending():
    assert statuses([{'event_type':'AUTHORIZATION_GRANTED'},{'event_type':'EXECUTION_COMPLETED'}])==['COMPLETED','COMPLETED','COMPLETED','PENDING']

def test_cycle_denial_marks_only_proven_failure():
    assert statuses([{'event_type':'AUTHORIZATION_DENIED'}])==['COMPLETED','FAILED','PENDING','PENDING']

def test_cycle_finalized_marks_audit_from_explicit_evidence():
    assert statuses([{'event_type':'AUDIT_FINALIZED'}])==['COMPLETED','PENDING','PENDING','COMPLETED']
