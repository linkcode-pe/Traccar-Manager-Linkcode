from manager.incident_decisions import intervention_durations

def e(t,ts): return {'event_type':t,'timestamp':ts}

def test_durations_require_both_bounds():
    d=intervention_durations([e('AUTHORIZATION_REQUESTED','2026-10-07T10:00:00Z')])
    assert all(v is None for v in d.values())

def test_durations_use_explicit_audit_timestamps():
    ev=[e('AUTHORIZATION_REQUESTED','2026-10-07T10:00:00Z'),e('AUTHORIZATION_GRANTED','2026-10-07T10:02:00Z'),e('EXECUTION_STARTED','2026-10-07T10:03:00Z'),e('EXECUTION_COMPLETED','2026-10-07T10:03:30Z'),e('AUDIT_FINALIZED','2026-10-07T10:04:00Z')]
    d=intervention_durations(ev)
    assert d['authorization_seconds']==120
    assert d['execution_seconds']==30
    assert d['audit_seconds']==30
    assert d['total_seconds']==240

def test_negative_or_invalid_time_is_never_reported():
    ev=[e('AUTHORIZATION_REQUESTED','2026-10-07T10:05:00Z'),e('AUTHORIZATION_GRANTED','2026-10-07T10:04:00Z'),e('EXECUTION_STARTED','bad'),e('EXECUTION_COMPLETED','2026-10-07T10:06:00Z')]
    d=intervention_durations(ev)
    assert d['authorization_seconds'] is None and d['execution_seconds'] is None
