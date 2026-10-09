import json
from pathlib import Path
from manager import incident_decisions as mod

def test_incident_reader_only_correlates_exact_metadata(tmp_path, monkeypatch):
    path=tmp_path/'audit.jsonl'
    rows=[
      {'event_type':'AUTHORIZATION_GRANTED','timestamp':'2026-10-07T11:00:00Z','status':'GRANTED','operation':'maintenance.logs.prepare','metadata':{'incident_id':'incident-e2e-safe'}},
      {'event_type':'EXECUTION_COMPLETED','timestamp':'2026-10-07T11:01:00Z','status':'COMPLETED','operation':'maintenance.logs.prepare','metadata':{'incident_id':'other'}},
      {'event_type':'AUDIT_FINALIZED','timestamp':'2026-10-07T11:02:00Z','status':'FINALIZED','operation':'maintenance.logs.prepare','metadata':{'incident_id':'incident-e2e-safe'}},
    ]
    path.write_text(''.join(json.dumps(x)+'\n' for x in rows)); path.chmod(0o640)
    monkeypatch.setattr(mod,'PATH',path)
    d=mod.read_incident_decisions('incident-e2e-safe')
    assert d['count']==2
    assert [x['event_type'] for x in d['events']]==['AUTHORIZATION_GRANTED','AUDIT_FINALIZED']
