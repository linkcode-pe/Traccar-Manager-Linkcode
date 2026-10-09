from datetime import datetime,timezone,timedelta
from manager.administrative_attention_history import administrative_attention_window

def iso(dt):return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def test_window_clips_to_real_coverage():
    now=datetime(2026,10,7,14,0,tzinfo=timezone.utc)
    events=[{'state':'NORMAL','started_at_utc':iso(now-timedelta(hours=2)),'ended_at_utc':None}]
    x=administrative_attention_window(events,24,now)
    assert x['covered_hours']==2.0 and x['coverage_percent']==8.3 and not x['complete_window']
    assert x['state_hours']['NORMAL']==2.0

def test_window_accumulates_states():
    now=datetime(2026,10,7,14,0,tzinfo=timezone.utc)
    events=[{'state':'NORMAL','started_at_utc':iso(now-timedelta(hours=4)),'ended_at_utc':iso(now-timedelta(hours=2))},{'state':'OBSERVATION','started_at_utc':iso(now-timedelta(hours=2)),'ended_at_utc':iso(now-timedelta(hours=1))},{'state':'ATTENTION','started_at_utc':iso(now-timedelta(hours=1)),'ended_at_utc':None}]
    x=administrative_attention_window(events,24,now)
    assert x['covered_hours']==4.0 and x['state_hours']=={'NORMAL':2.0,'OBSERVATION':1.0,'ATTENTION':1.0}
