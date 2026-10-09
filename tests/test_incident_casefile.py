from manager.preventive_diagnostics import incident_casefile

def test_casefile_preserves_real_timeline_only():
    e={'id':'x','kind':'component_growth','component':'binlogs','severity':'WARNING','status':'OPEN','opened_at_utc':'2026-10-07T04:00:00Z','updated_at_utc':'2026-10-07T05:00:00Z','summary':'Binlogs'}
    d=incident_casefile(e,{'storage_protection':{'binlogs':{'status':'PROTECTED','retention_days':7,'used_bytes':2147483648}}})
    assert [x['event'] for x in d['timeline']]==['DETECTED','OBSERVED']
    assert d['persistent'] is True and d['read_only'] is True
    assert d['diagnostic']['runbook'][0]['live_status']=='VERIFIED'

def test_resolved_casefile_has_resolution_event():
    e={'id':'x','kind':'capacity_horizon','component':'filesystem','severity':'WARNING','status':'RESOLVED','opened_at_utc':'2026-10-07T01:00:00Z','updated_at_utc':'2026-10-07T02:00:00Z','resolved_at_utc':'2026-10-07T03:00:00Z'}
    d=incident_casefile(e,{})
    assert d['timeline'][-1]['event']=='RESOLVED'
