from datetime import datetime,timezone,timedelta
from manager.administrative_attention_history import administrative_attention_index
def iso(x):return x.strftime('%Y-%m-%dT%H:%M:%SZ')
def event(state,a):return {'state':state,'started_at_utc':iso(a),'ended_at_utc':None}

def test_index_normal_collecting_is_not_penalized():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc);x=administrative_attention_index([event('NORMAL',n-timedelta(hours=1))],[],n)
    assert x['score']==100 and x['label']=='Óptimo'

def test_index_penalties_are_explainable_and_bounded():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc)
    interventions=[{'result_code':'AUTHORIZED','stall':{'stalled':True},'last_event_at':iso(n-timedelta(hours=3))}]+[{'result_code':'FAILED','stall':{'stalled':False},'last_event_at':iso(n-timedelta(hours=1))} for _ in range(4)]
    x=administrative_attention_index([event('ATTENTION',n-timedelta(hours=6))],interventions,n)
    assert x['score']==30 and x['label']=='Crítico'
    assert {f['code'] for f in x['factors'] if f['penalty']>0}=={'current_state','stalled','failed_24h'}

def test_old_failure_not_penalized():
    n=datetime(2026,10,7,14,tzinfo=timezone.utc);x=administrative_attention_index([event('NORMAL',n-timedelta(hours=6))],[{'result_code':'FAILED','stall':{'stalled':False},'last_event_at':iso(n-timedelta(hours=25))}],n)
    assert x['score']==100
