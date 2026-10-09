from datetime import datetime, timezone
from manager.operational_health_history import operational_availability

NOW=datetime(2026,10,7,12,0,tzinfo=timezone.utc)

def test_availability_partial_coverage_is_not_extrapolated():
    events=[{'state':'OBSERVATION','started_at_utc':'2026-10-07T06:00:00Z','ended_at_utc':None}]
    d=operational_availability(events,24,NOW)
    assert d['covered_hours']==6.0
    assert d['coverage_percent']==25.0
    assert d['stable_percent']==100.0
    assert d['complete_window'] is False

def test_availability_counts_degraded_time():
    events=[
      {'state':'HEALTHY','started_at_utc':'2026-10-06T12:00:00Z','ended_at_utc':'2026-10-07T06:00:00Z'},
      {'state':'ATTENTION','started_at_utc':'2026-10-07T06:00:00Z','ended_at_utc':None},
    ]
    d=operational_availability(events,24,NOW)
    assert d['coverage_percent']==100.0
    assert d['stable_percent']==75.0
    assert d['degraded_percent']==25.0
    assert d['state_hours']['ATTENTION']==6.0
    assert d['complete_window'] is True

def test_availability_clips_events_to_window():
    events=[{'state':'HEALTHY','started_at_utc':'2026-09-01T00:00:00Z','ended_at_utc':None}]
    d=operational_availability(events,168,NOW)
    assert d['covered_hours']==168.0
    assert d['coverage_percent']==100.0
    assert d['stable_percent']==100.0
