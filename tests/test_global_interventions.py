import json
import manager.incident_decisions as m

def row(incident,auth,event='AUTHORIZATION_GRANTED'):
    return json.dumps({'event_type':event,'timestamp':'2026-10-07T10:00:00Z','operation':'maintenance.logs.execute','authorization_id':auth,'metadata':{'incident_id':incident}})

def test_global_only_explicit_incident_links(tmp_path,monkeypatch):
    p=tmp_path/'audit.jsonl';p.write_text(row('inc-a','a1')+'\n'+row('inc-b','b1','EXECUTION_COMPLETED')+'\n'+json.dumps({'event_type':'AUTHORIZATION_GRANTED','authorization_id':'x'})+'\n')
    monkeypatch.setattr(m,'PATH',p)
    d=m.read_global_interventions()
    assert d['count']==2 and {x['incident_id'] for x in d['interventions']}=={'inc-a','inc-b'}
    assert d['read_only'] is True and d['linked_by']=='incident_id'
