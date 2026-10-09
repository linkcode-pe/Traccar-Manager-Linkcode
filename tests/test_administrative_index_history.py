import json
import manager.administrative_index_history as m
from manager.administrative_index_history import read_administrative_index_history

def test_missing_index_history(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'PATH',tmp_path/'missing.json')
    assert read_administrative_index_history()['events']==[]

def test_index_history_newest_first(tmp_path,monkeypatch):
    p=tmp_path/'i.json';monkeypatch.setattr(m,'PATH',p)
    p.write_text(json.dumps({'events':[{'score':100,'label':'Óptimo','cause':'ok','started_at_utc':'2026-10-07T10:00:00Z','updated_at_utc':'2026-10-07T11:00:00Z','ended_at_utc':'2026-10-07T11:00:00Z'},{'score':85,'label':'Estable','cause':'factor','started_at_utc':'2026-10-07T11:00:00Z','updated_at_utc':'2026-10-07T12:00:00Z','ended_at_utc':None}]}))
    d=read_administrative_index_history();assert d['events'][0]['score']==85 and d['count']==2 and d['read_only']
