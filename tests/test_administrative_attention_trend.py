from datetime import datetime,timezone,timedelta
from manager.administrative_attention_history import administrative_attention_trend

def iso(x):return x.strftime('%Y-%m-%dT%H:%M:%SZ')
def ev(state,a,b=None):return {'state':state,'started_at_utc':iso(a),'ended_at_utc':iso(b) if b else None}

def test_trend_collects_before_six_hours():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc)
    assert administrative_attention_trend([ev('NORMAL',n-timedelta(hours=2))],n)['status']=='COLLECTING'

def test_trend_stable():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc)
    assert administrative_attention_trend([ev('NORMAL',n-timedelta(hours=6))],n)['status']=='STABLE'

def test_trend_deteriorating():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc);s=n-timedelta(hours=6);m=n-timedelta(hours=3)
    assert administrative_attention_trend([ev('NORMAL',s,m),ev('ATTENTION',m)],n)['status']=='DETERIORATING'

def test_trend_improving():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc);s=n-timedelta(hours=6);m=n-timedelta(hours=3)
    assert administrative_attention_trend([ev('ATTENTION',s,m),ev('NORMAL',m)],n)['status']=='IMPROVING'
