from manager.preventive_diagnostics import diagnose_incident, diagnostic_center

def test_binlog_growth_diagnostic_is_conservative():
    e={'id':'x','kind':'component_growth','component':'binlogs','severity':'WARNING','status':'OPEN','detail':'Tendencia positiva'}
    d=diagnose_incident(e)
    assert d['action_mode']=='RECOMMENDATION_ONLY'
    assert '7 días' in d['recommendation']
    assert 'limpieza general' not in d['recommendation'].lower()

def test_slo_diagnostic_explains_budget_risk():
    e={'id':'s','kind':'slo_burn_24h','component':'slo_24_h','severity':'WARNING','status':'OPEN','detail':'Burn rate 2x'}
    d=diagnose_incident(e)
    assert '99.9%' in d['impact']
    assert 'Burn rate' in d['evidence']

def test_center_only_exposes_open_incidents():
    rows=[{'id':'a','kind':'component_growth','component':'binlogs','severity':'WARNING','status':'OPEN'},
          {'id':'b','kind':'capacity_horizon','component':'filesystem','severity':'WARNING','status':'RESOLVED'}]
    d=diagnostic_center(rows)
    assert d['count']==1
    assert d['diagnostics'][0]['incident_id']=='a'
    assert d['read_only'] is True
