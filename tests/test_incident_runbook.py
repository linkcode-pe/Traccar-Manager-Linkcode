from manager.preventive_diagnostics import diagnose_incident

def test_binlog_runbook_has_safe_order_and_auth_gate():
    d=diagnose_incident({'id':'x','kind':'component_growth','component':'binlogs','severity':'WARNING','status':'OPEN'})
    steps=d['runbook']
    assert [x['step'] for x in steps]==['Protección','Retención','Tamaño','Tendencia','Decisión']
    assert all(x['mode']=='READ_ONLY' for x in steps[:-1])
    assert steps[-1]['mode']=='ADMIN_AUTHORIZATION'

def test_slo_runbook_requires_auth_for_correction():
    d=diagnose_incident({'id':'s','kind':'slo_burn_24h','component':'slo_24_h','severity':'WARNING','status':'OPEN'})
    assert d['runbook'][-1]['mode']=='ADMIN_AUTHORIZATION'
    assert any(x['step']=='Burn rate' for x in d['runbook'])
