"""Conservative read-only diagnostics for persistent preventive incidents."""
from __future__ import annotations

def _component_label(component):
    return {
        'binlogs':'Binlogs de MySQL','mysql_core':'Datos principales de MySQL',
        'traccar_logs':'Logs de Traccar','journal':'Journal del sistema',
        'manager_history':'Histórico del Manager','other':'Uso general del disco',
        'filesystem':'Sistema de archivos','slo_24_h':'SLO de 24 horas',
        'slo_7_días':'SLO de 7 días',
    }.get(component, component.replace('_',' ').strip().capitalize() if component else 'Componente no identificado')

def _runbook(kind,component):
    if kind=='component_growth' and component=='binlogs':
        return [
            {'step':'Protección','status':'AUTO_CHECK','mode':'READ_ONLY','description':'Confirmar política protegida de binlogs y estado del auditor.'},
            {'step':'Retención','status':'VERIFIED_POLICY','mode':'READ_ONLY','description':'Política configurada: 7 días. Verificar que permanezca protegida.'},
            {'step':'Tamaño','status':'AUTO_CHECK','mode':'READ_ONLY','description':'Consultar tamaño agregado de binlogs desde el snapshot del auditor.'},
            {'step':'Tendencia','status':'OBSERVING','mode':'READ_ONLY','description':'Comparar crecimiento persistente antes de intervenir.'},
            {'step':'Decisión','status':'AUTH_REQUIRED','mode':'ADMIN_AUTHORIZATION','description':'Cualquier cambio de retención o purga requiere preparación, autorización y auditoría.'},
        ]
    if kind in {'slo_burn_24h','slo_burn_7d'}:
        return [
            {'step':'Cobertura','status':'AUTO_CHECK','mode':'READ_ONLY','description':'Confirmar que la ventana tenga línea base suficiente.'},
            {'step':'Burn rate','status':'AUTO_CHECK','mode':'READ_ONLY','description':'Verificar ritmo de consumo y presupuesto restante.'},
            {'step':'Incidentes origen','status':'OBSERVING','mode':'READ_ONLY','description':'Identificar condiciones Atención/Crítico que consumen presupuesto.'},
            {'step':'Decisión','status':'AUTH_REQUIRED','mode':'ADMIN_AUTHORIZATION','description':'Toda corrección del componente origen requiere autorización separada.'},
        ]
    return [
        {'step':'Evidencia','status':'AUTO_CHECK','mode':'READ_ONLY','description':'Confirmar evidencia persistente y estado actual.'},
        {'step':'Diagnóstico','status':'OBSERVING','mode':'READ_ONLY','description':'Validar causa probable antes de intervenir.'},
        {'step':'Decisión','status':'AUTH_REQUIRED','mode':'ADMIN_AUTHORIZATION','description':'Cualquier modificación requiere autorización administrativa separada.'},
    ]

def diagnose_incident(event, server=None):
    kind=str(event.get('kind') or '')
    component=str(event.get('component') or '')
    detail=str(event.get('detail') or '')
    base={'incident_id':event.get('id'),'kind':kind,'status':event.get('status'),'severity':event.get('severity'),'component':component,'component_label':_component_label(component),'read_only':True,'action_mode':'RECOMMENDATION_ONLY'}
    if kind=='component_growth':
        cause=f"Crecimiento sostenido detectado en {_component_label(component)}."
        evidence=detail or 'La regresión temporal del componente supera el umbral preventivo.'
        if component=='binlogs':
            recommendation='Mantener la retención de binlogs bajo observación y verificar que la política de 7 días continúe protegida antes de considerar cualquier ajuste.'
            impact='Puede aumentar progresivamente el uso de disco si el ritmo se mantiene.'
        elif component=='traccar_logs':
            recommendation='Revisar crecimiento y retención de logs sin eliminar el log activo ni archivos fuera de la política autorizada.'
            impact='Puede reducir el espacio libre disponible para Traccar y el sistema.'
        else:
            recommendation='Confirmar la tendencia durante una ventana mayor antes de autorizar mantenimiento sobre el componente.'
            impact='Puede elevar gradualmente la presión de almacenamiento.'
    elif kind=='capacity_horizon':
        cause='La tendencia del disco proyecta aproximación a un umbral de capacidad.'
        evidence=detail or 'Proyección basada en el histórico agregado de uso de disco.'
        recommendation='Identificar primero el componente dominante y aplicar únicamente una medida específica y reversible; no ejecutar limpieza general.'
        impact='Riesgo futuro de pérdida de margen operativo si la tendencia continúa.'
    elif kind in {'slo_burn_24h','slo_burn_7d'}:
        cause='El ritmo de tiempo degradado proyecta consumir el presupuesto de error SLO.'
        evidence=detail or 'Burn rate calculado sobre la ventana operacional persistente.'
        recommendation='Revisar los incidentes técnicos activos que originan Atención/Crítico antes de considerar cualquier acción correctiva.'
        impact='El objetivo de estabilidad 99.9% podría incumplirse al cierre de la ventana.'
    else:
        cause='Condición preventiva persistente detectada por el auditor.'
        evidence=detail or 'Existe evidencia persistente asociada al incidente.'
        recommendation='Revisar la evidencia y confirmar la causa antes de autorizar cambios administrativos.'
        impact='Impacto pendiente de clasificación específica.'
    runbook=_runbook(kind,component)
    if kind=='component_growth' and component=='binlogs' and server:
        p=server.get('storage_protection') or {}; b=p.get('binlogs') or {}
        live=[]
        for r in runbook:
            r=dict(r)
            if r['step']=='Protección':
                ok=b.get('status')=='PROTECTED'; r['live_status']='VERIFIED' if ok else 'ATTENTION'; r['live_detail']='Protegida por auditor' if ok else 'Protección no confirmada'
            elif r['step']=='Retención':
                days=b.get('retention_days'); ok=days==7; r['live_status']='VERIFIED' if ok else ('PENDING' if days is None else 'ATTENTION'); r['live_detail']='7 días verificados' if ok else ('Dato no disponible' if days is None else str(days)+' días configurados')
            elif r['step']=='Tamaño':
                size=b.get('used_bytes'); r['live_status']='VERIFIED' if isinstance(size,(int,float)) else 'PENDING'; r['live_detail']=(str(round(size/1073741824,2))+' GiB observados') if isinstance(size,(int,float)) else 'Tamaño pendiente de snapshot'
            elif r['step']=='Tendencia':
                r['live_status']='OBSERVING'; r['live_detail']='Incidente de crecimiento activo'
            else:
                r['live_status']='AUTH_REQUIRED'; r['live_detail']='Bloqueado hasta autorización administrativa'
            live.append(r)
        runbook=live
    else:
        for r in runbook:
            r['live_status']='AUTH_REQUIRED' if r['mode']=='ADMIN_AUTHORIZATION' else ('OBSERVING' if r['status']=='OBSERVING' else 'PENDING')
            r['live_detail']='Requiere autorización administrativa' if r['mode']=='ADMIN_AUTHORIZATION' else 'Pendiente de verificación contextual'
    return {**base,'probable_cause':cause,'evidence':evidence,'impact':impact,'recommendation':recommendation,'runbook':runbook}

def diagnostic_center(events, server=None):
    active=[diagnose_incident(e,server) for e in events if e.get('status')=='OPEN']
    rank={'CRITICAL':3,'WARNING':2}
    active.sort(key=lambda x:rank.get(x.get('severity'),1),reverse=True)
    return {'diagnostics':active,'count':len(active),'read_only':True,'action_mode':'RECOMMENDATION_ONLY'}

def incident_casefile(event, server=None):
    diag=diagnose_incident(event,server)
    timeline=[]
    if event.get('opened_at_utc'):
        timeline.append({'event':'DETECTED','label':'Detectado','at_utc':event['opened_at_utc']})
    if event.get('updated_at_utc') and event.get('updated_at_utc')!=event.get('opened_at_utc'):
        timeline.append({'event':'OBSERVED','label':'Última observación','at_utc':event['updated_at_utc']})
    if event.get('resolved_at_utc'):
        timeline.append({'event':'RESOLVED','label':'Resuelto','at_utc':event['resolved_at_utc']})
    return {
        'incident_id':event.get('id'),'summary':event.get('summary'),'status':event.get('status'),
        'severity':event.get('severity'),'operational_priority':event.get('operational_priority','OBSERVE'),
        'opened_at_utc':event.get('opened_at_utc'),'updated_at_utc':event.get('updated_at_utc'),
        'resolved_at_utc':event.get('resolved_at_utc'),'timeline':timeline,'diagnostic':diag,
        'persistent':True,'read_only':True,
    }
