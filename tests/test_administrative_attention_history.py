from datetime import datetime,timezone,timedelta
from manager.administrative_attention_history import read_administrative_attention_history
import manager.administrative_attention_history as m
import json, tempfile
from pathlib import Path

def test_missing_store_is_empty(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'PATH',tmp_path/'missing.json')
    assert read_administrative_attention_history()['events']==[]

def test_history_is_newest_first_and_sanitized(tmp_path,monkeypatch):
    p=tmp_path/'h.json';monkeypatch.setattr(m,'PATH',p)
    p.write_text(json.dumps({'schema_version':1,'events':[{'state':'NORMAL','label':'Normal','cause':'ok','started_at_utc':'2026-10-07T10:00:00Z','updated_at_utc':'2026-10-07T10:05:00Z','ended_at_utc':'2026-10-07T10:05:00Z'},{'state':'OBSERVATION','label':'Observación','cause':'1 intervención en curso','started_at_utc':'2026-10-07T10:05:00Z','updated_at_utc':'2026-10-07T10:06:00Z','ended_at_utc':None}]}))
    d=read_administrative_attention_history()
    assert d['read_only'] is True and d['events'][0]['state']=='OBSERVATION' and d['count']==2

def test_rejects_unexpected_fields(tmp_path,monkeypatch):
    p=tmp_path/'h.json';monkeypatch.setattr(m,'PATH',p)
    p.write_text(json.dumps({'events':[{'state':'NORMAL','secret':'x'}]}))
    assert read_administrative_attention_history()['events']==[]
