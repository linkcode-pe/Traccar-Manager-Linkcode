from manager.incident_decisions import intervention_summary

def test_summary_reports_furthest_evidenced_stage():
    item={'state':{'code':'AUTHORIZED','label':'Autorizada'},'cycle':[{'label':'Preparación','status':'COMPLETED'},{'label':'Autorización','status':'COMPLETED'},{'label':'Ejecución','status':'PENDING'},{'label':'Auditoría','status':'PENDING'}],'durations':{'total_seconds':None},'events':[{},{}],'operation':'maintenance.logs'}
    s=intervention_summary(item)
    assert s['stage_reached']=='Autorización' and s['event_count']==2 and s['audited'] is True

def test_summary_failure_stage_is_not_hidden():
    item={'state':{'code':'FAILED','label':'Fallida'},'cycle':[{'label':'Preparación','status':'COMPLETED'},{'label':'Autorización','status':'COMPLETED'},{'label':'Ejecución','status':'FAILED'},{'label':'Auditoría','status':'PENDING'}],'durations':{'total_seconds':12},'events':[{}]}
    s=intervention_summary(item)
    assert s['stage_reached']=='Ejecución' and s['result_code']=='FAILED' and s['total_seconds']==12
