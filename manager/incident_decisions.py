"""Bounded read-only incident-linked administrative decision reader."""
from __future__ import annotations
from collections import deque
from pathlib import Path
import json, os, stat
from datetime import datetime, timezone
PATH=Path('/var/lib/traccar-manager-worker/audit.jsonl')
MAX_BYTES=8*1024*1024
MAX_LINES=600
ALLOWED={'AUTHORIZATION_REQUESTED','AUTHORIZATION_GRANTED','AUTHORIZATION_DENIED','EXECUTION_STARTED','EXECUTION_COMPLETED','EXECUTION_FAILED','EXECUTION_DENIED','AUDIT_FINALIZED'}

def _event_time(events, event_type):
    values=[]
    for e in events:
        if not isinstance(e,dict) or e.get('event_type')!=event_type: continue
        raw=e.get('timestamp')
        if not isinstance(raw,str): continue
        try: dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
        except ValueError: continue
        if dt.tzinfo is None: continue
        values.append(dt.astimezone(timezone.utc))
    return min(values) if values else None

def intervention_durations(events):
    requested=_event_time(events,'AUTHORIZATION_REQUESTED')
    granted=_event_time(events,'AUTHORIZATION_GRANTED')
    denied=_event_time(events,'AUTHORIZATION_DENIED')
    started=_event_time(events,'EXECUTION_STARTED')
    completed=_event_time(events,'EXECUTION_COMPLETED')
    failed=_event_time(events,'EXECUTION_FAILED') or _event_time(events,'EXECUTION_DENIED')
    finalized=_event_time(events,'AUDIT_FINALIZED')
    def elapsed(a,b):
        if a is None or b is None or b<a: return None
        return round((b-a).total_seconds(),3)
    auth_end=granted or denied
    execution_end=completed or failed
    return {
      'preparation_seconds': elapsed(requested,auth_end),
      'authorization_seconds': elapsed(requested,auth_end),
      'execution_seconds': elapsed(started,execution_end),
      'audit_seconds': elapsed(execution_end,finalized),
      'total_seconds': elapsed(requested,finalized),
    }

def intervention_cycle(events):
    types={e.get('event_type') for e in events if isinstance(e,dict)}
    def stage(key,label,done,failed=False):
        return {'key':key,'label':label,'status':'FAILED' if failed else ('COMPLETED' if done else 'PENDING')}
    return [
        stage('preparation','Preparación',bool(types & {'AUTHORIZATION_REQUESTED','AUTHORIZATION_GRANTED','AUTHORIZATION_DENIED','EXECUTION_STARTED','EXECUTION_COMPLETED','EXECUTION_FAILED','EXECUTION_DENIED','AUDIT_FINALIZED'})),
        stage('authorization','Autorización','AUTHORIZATION_GRANTED' in types,'AUTHORIZATION_DENIED' in types),
        stage('execution','Ejecución','EXECUTION_COMPLETED' in types,bool(types & {'EXECUTION_FAILED','EXECUTION_DENIED'})),
        stage('audit','Auditoría','AUDIT_FINALIZED' in types),
    ]

def intervention_state(events):
    types={e.get('event_type') for e in events if isinstance(e,dict)}
    if types & {'EXECUTION_FAILED','EXECUTION_DENIED','AUTHORIZATION_DENIED'}:
        return {'code':'FAILED','label':'Fallida'}
    if 'EXECUTION_COMPLETED' in types:
        return {'code':'EXECUTED','label':'Ejecutada'}
    if 'AUTHORIZATION_GRANTED' in types:
        return {'code':'AUTHORIZED','label':'Autorizada'}
    if types & {'AUTHORIZATION_REQUESTED','EXECUTION_STARTED','AUDIT_FINALIZED'}:
        return {'code':'PREPARED','label':'Preparada'}
    return {'code':'NONE','label':'Sin intervención'}

def intervention_summary(item):
    cycle=item.get('cycle') if isinstance(item,dict) else []
    reached='Sin iniciar'
    for stage in cycle or []:
        if stage.get('status') in {'COMPLETED','FAILED'}:
            reached=stage.get('label') or reached
    state=item.get('state') if isinstance(item,dict) else {}
    durations=item.get('durations') if isinstance(item,dict) else {}
    events=item.get('events') if isinstance(item,dict) else []
    return {'result':state.get('label','Sin intervención'),'result_code':state.get('code','NONE'),'stage_reached':reached,'event_count':len(events or []),'total_seconds':(durations or {}).get('total_seconds'),'audited':bool(events),'operation':item.get('operation') if isinstance(item,dict) else None}

def intervention_history(events):
    """Agrupa eventos auditados sin mezclar intervenciones ambiguas."""
    groups = {}
    order = []

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue

        authorization_id = event.get("authorization_id")
        job_id = event.get("job_id")
        request_id = event.get("request_id")

        if isinstance(authorization_id, str) and authorization_id:
            key = "authorization:" + authorization_id
        elif isinstance(job_id, str) and job_id:
            key = "job:" + job_id
        elif isinstance(request_id, str) and request_id:
            key = "request:" + request_id
        else:
            # Fail-closed: un evento sin identificador suficiente queda aislado.
            key = "isolated:" + str(index) + ":" + str(
                event.get("event_id") or "event"
            )

        if key not in groups:
            groups[key] = []
            order.append(key)

        groups[key].append(event)

    result = []

    for key in order:
        grouped_events = groups[key]

        result.append({
            "intervention_key": key,
            "authorization_id": next(
                (
                    e.get("authorization_id")
                    for e in grouped_events
                    if e.get("authorization_id")
                ),
                None,
            ),
            "request_id": next(
                (
                    e.get("request_id")
                    for e in grouped_events
                    if e.get("request_id")
                ),
                None,
            ),
            "job_id": next(
                (
                    e.get("job_id")
                    for e in grouped_events
                    if e.get("job_id")
                ),
                None,
            ),
            "operation": next(
                (
                    e.get("operation")
                    for e in grouped_events
                    if e.get("operation")
                ),
                None,
            ),
            "state": intervention_state(grouped_events),
            "cycle": intervention_cycle(grouped_events),
            "durations": intervention_durations(grouped_events),
            "events": grouped_events,
            "event_count": len(grouped_events),
        })
        result[-1]["summary"] = intervention_summary(result[-1])

    # Máximo 20 intervenciones y más recientes primero.
    return list(reversed(result[-20:]))

def read_incident_decisions(incident_id):
    if not isinstance(incident_id,str) or not incident_id or len(incident_id)>160: return {'events':[],'count':0,'linked_by':'incident_id','read_only':True,'intervention_state':intervention_state([]),'intervention_cycle':intervention_cycle([]),'intervention_durations':intervention_durations([]),'interventions':intervention_history([])}
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES: raise ValueError('invalid audit ledger')
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            with os.fdopen(fd,'r',encoding='utf-8') as f:
                fd=-1; lines=deque(f,maxlen=MAX_LINES)
        finally:
            if fd>=0: os.close(fd)
        out=[]
        for line in lines:
            try: row=json.loads(line)
            except json.JSONDecodeError: continue
            meta=row.get('metadata') if isinstance(row,dict) else None
            if not isinstance(meta,dict) or meta.get('incident_id')!=incident_id: continue
            if row.get('event_type') not in ALLOWED: continue
            out.append({'event_type':row.get('event_type'),'timestamp':row.get('timestamp'),'status':row.get('status'),'operation':row.get('operation'),'result_code':row.get('result_code'),'authorization_id':row.get('authorization_id'),'request_id':row.get('request_id'),'job_id':row.get('job_id'),'event_id':row.get('event_id'),'ledger_sequence':row.get('ledger_sequence')})
        events=out[-50:]; return {'events':events,'count':len(out),'linked_by':'incident_id','read_only':True,'intervention_state':intervention_state(events),'intervention_cycle':intervention_cycle(events),'intervention_durations':intervention_durations(events),'interventions':intervention_history(events)}
    except FileNotFoundError:
        return {'events':[],'count':0,'linked_by':'incident_id','read_only':True,'intervention_state':intervention_state([]),'intervention_cycle':intervention_cycle([]),'intervention_durations':intervention_durations([])}


def read_global_interventions():
    """Bounded read-only view of explicitly incident-linked interventions."""
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES:
            raise ValueError("invalid audit ledger")
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            with os.fdopen(fd,'r',encoding='utf-8') as f:
                fd=-1; lines=deque(f,maxlen=MAX_LINES)
        finally:
            if fd>=0: os.close(fd)
        by_incident={}
        for line in lines:
            try: row=json.loads(line)
            except json.JSONDecodeError: continue
            if not isinstance(row,dict) or row.get('event_type') not in ALLOWED: continue
            meta=row.get('metadata')
            incident_id=meta.get('incident_id') if isinstance(meta,dict) else None
            if not isinstance(incident_id,str) or not incident_id or len(incident_id)>160: continue
            event={'event_type':row.get('event_type'),'timestamp':row.get('timestamp'),'status':row.get('status'),'operation':row.get('operation'),'result_code':row.get('result_code'),'authorization_id':row.get('authorization_id'),'request_id':row.get('request_id'),'job_id':row.get('job_id'),'event_id':row.get('event_id'),'ledger_sequence':row.get('ledger_sequence')}
            by_incident.setdefault(incident_id,[]).append(event)
        items=[]
        for incident_id,events in by_incident.items():
            for intervention in intervention_history(events):
                summary=dict(intervention.get('summary') or {})
                summary['incident_id']=incident_id
                summary['authorization_id']=intervention.get('authorization_id')
                summary['intervention_key']=intervention.get('intervention_key')
                timestamps=[e.get('timestamp') for e in intervention.get('events',[]) if isinstance(e.get('timestamp'),str)]
                summary['last_event_at']=max(timestamps) if timestamps else None
                summary['stall']=intervention_stall(summary)
                summary['cycle']=intervention.get('cycle') or []
                summary['durations']=intervention.get('durations') or {}
                summary['events']=intervention.get('events') or []
                items.append(summary)
        items.sort(key=lambda x:x.get('last_event_at') or '',reverse=True)
        return {'interventions':items[:50],'count':len(items),'read_only':True,'linked_by':'incident_id'}
    except FileNotFoundError:
        return {'interventions':[],'count':0,'read_only':True,'linked_by':'incident_id'}


def intervention_stall(summary, now=None):
    """Read-only stalled-state classification from audited last-event time."""
    if not isinstance(summary,dict) or summary.get('result_code') not in {'PREPARED','AUTHORIZED'}:
        return {'stalled':False,'threshold_hours':None,'age_hours':None,'reason':None}
    raw=summary.get('last_event_at')
    if not isinstance(raw,str):
        return {'stalled':False,'threshold_hours':None,'age_hours':None,'reason':None}
    try: last=datetime.fromisoformat(raw.replace('Z','+00:00'))
    except ValueError: return {'stalled':False,'threshold_hours':None,'age_hours':None,'reason':None}
    if last.tzinfo is None: return {'stalled':False,'threshold_hours':None,'age_hours':None,'reason':None}
    current=now or datetime.now(timezone.utc)
    age=max(0.0,(current.astimezone(timezone.utc)-last.astimezone(timezone.utc)).total_seconds()/3600.0)
    threshold=2 if summary.get('result_code')=='AUTHORIZED' else 6
    stalled=age>=threshold
    label='Autorizada sin ejecución' if summary.get('result_code')=='AUTHORIZED' else 'Preparada sin autorización'
    return {'stalled':stalled,'threshold_hours':threshold,'age_hours':round(age,2),'reason':label if stalled else None}
