from datetime import datetime, timezone
from manager.operational_health_history import operational_availability
NOW=datetime(2026,10,7,12,0,tzinfo=timezone.utc)

def test_forecast_collects_before_minimum_baseline():
    e=[{'state':'OBSERVATION','started_at_utc':'2026-10-07T11:00:00Z','ended_at_utc':None}]
    d=operational_availability(e,24,NOW)
    assert d['forecast_status']=='COLLECTING'
    assert d['burn_rate'] is None

def test_forecast_stable_after_baseline_without_degradation():
    e=[{'state':'HEALTHY','started_at_utc':'2026-10-07T06:00:00Z','ended_at_utc':None}]
    d=operational_availability(e,24,NOW)
    assert d['forecast_status']=='STABLE' and d['burn_rate']==0.0

def test_forecast_detects_budget_burn_risk():
    e=[
      {'state':'HEALTHY','started_at_utc':'2026-10-07T06:00:00Z','ended_at_utc':'2026-10-07T11:59:00Z'},
      {'state':'ATTENTION','started_at_utc':'2026-10-07T11:59:00Z','ended_at_utc':None},
    ]
    d=operational_availability(e,24,NOW)
    assert d['forecast_status']=='AT_RISK'
    assert d['burn_rate']>1
    assert d['projected_consumed_minutes']>d['error_budget_minutes']
