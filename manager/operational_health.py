"""Conservative aggregate operational health state."""
from __future__ import annotations

def operational_health(server, incidents):
    factors=[]
    level=0
    def add(rank,code,label,detail):
        nonlocal level
        level=max(level,rank); factors.append({'rank':rank,'code':code,'label':label,'detail':detail})
    disk=float(server.get('disk_used_percent') or 0)
    mem_total=int(server.get('memory_total_bytes') or 0); mem_used=int(server.get('memory_used_bytes') or 0)
    memory=(mem_used*100/mem_total) if mem_total else 0
    if disk>=90:add(3,'disk','Disco crítico',f'{disk:.1f}% utilizado')
    elif disk>=80:add(2,'disk','Disco en atención',f'{disk:.1f}% utilizado')
    if memory>=95:add(3,'memory','Memoria crítica',f'{memory:.1f}% utilizada')
    elif memory>=85:add(2,'memory','Memoria elevada',f'{memory:.1f}% utilizada')
    p=server.get('storage_protection')
    if not p:add(3,'storage_snapshot','Auditoría no disponible','Sin snapshot reciente de protecciones')
    else:
        if p.get('journal',{}).get('status')!='PROTECTED':add(3,'journal','Journal sin protección','Política no verificada')
        if p.get('binlogs',{}).get('status')!='PROTECTED':add(3,'binlogs','Binlogs sin protección','Política no verificada')
        if p.get('database',{}).get('status')!='HEALTHY':add(3,'database','Base de datos no verificable','Metadatos no saludables')
        for name,state in (p.get('services') or {}).items():
            ok=state.get('active_state')=='active' and state.get('sub_state') in {'running','waiting'}
            if not ok:add(3,'service_'+name,'Servicio requiere atención',name)
    for e in incidents:
        if e.get('status')!='OPEN':continue
        sev=e.get('severity'); op=e.get('operational_priority','OBSERVE')
        if sev=='CRITICAL' or op=='CRITICAL':rank=3
        elif op=='HIGH':rank=2
        elif op=='MEDIUM':rank=2
        else:rank=1
        add(rank,'incident_'+str(e.get('kind','unknown')),e.get('summary','Incidente preventivo'),op)
    states={0:'HEALTHY',1:'OBSERVATION',2:'ATTENTION',3:'CRITICAL'}
    labels={0:'Saludable',1:'Observación',2:'Atención',3:'Crítico'}
    factors.sort(key=lambda x:x['rank'],reverse=True)
    cause=factors[0] if factors else {'code':'none','label':'Sin incidencias','detail':'Todos los controles dentro de parámetros'}
    return {'state':states[level],'label':labels[level],'cause':cause,'factors':[{'code':x['code'],'label':x['label'],'detail':x['detail']} for x in factors[:5]],'read_only':True}
