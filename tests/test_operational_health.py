from manager.operational_health import operational_health

def base():
    return {'disk_used_percent':50,'memory_total_bytes':100,'memory_used_bytes':40,'storage_protection':{'journal':{'status':'PROTECTED'},'binlogs':{'status':'PROTECTED'},'database':{'status':'HEALTHY'},'services':{'traccar':{'active_state':'active','sub_state':'running'}}}}

def test_health_is_healthy_without_factors():
    assert operational_health(base(),[])['state']=='HEALTHY'

def test_warning_incident_is_observation():
    e={'status':'OPEN','severity':'WARNING','operational_priority':'OBSERVE','kind':'growth','summary':'growth'}
    assert operational_health(base(),[e])['state']=='OBSERVATION'

def test_persistent_warning_is_attention_not_critical():
    e={'status':'OPEN','severity':'WARNING','operational_priority':'HIGH','kind':'growth','summary':'growth'}
    assert operational_health(base(),[e])['state']=='ATTENTION'

def test_technical_failure_is_critical():
    s=base();s['storage_protection']['services']['traccar']['active_state']='failed'
    assert operational_health(s,[])['state']=='CRITICAL'
