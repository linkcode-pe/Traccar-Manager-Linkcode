from datetime import datetime, timezone
from manager.operational_health_history import operational_availability
NOW=datetime(2026,10,7,12,0,tzinfo=timezone.utc)

def test_24h_error_budget_for_999_is_144_minutes():
    e=[{'state':'HEALTHY','started_at_utc':'2026-10-06T12:00:00Z','ended_at_utc':None}]
    d=operational_availability(e,24,NOW)
    assert d['error_budget_minutes']==1.44
    assert d['error_budget_remaining_minutes']==1.44
    assert d['error_budget_status']=='WITHIN_BUDGET'

def test_partial_window_never_claims_slo_compliance():
    e=[{'state':'OBSERVATION','started_at_utc':'2026-10-07T11:00:00Z','ended_at_utc':None}]
    d=operational_availability(e,24,NOW)
    assert d['stable_percent']==100.0
    assert d['error_budget_status']=='PROVISIONAL'

def test_degraded_full_window_exhausts_budget():
    e=[{'state':'ATTENTION','started_at_utc':'2026-10-06T12:00:00Z','ended_at_utc':None}]
    d=operational_availability(e,24,NOW)
    assert d['error_budget_remaining_minutes']==0.0
    assert d['error_budget_status']=='EXHAUSTED'
