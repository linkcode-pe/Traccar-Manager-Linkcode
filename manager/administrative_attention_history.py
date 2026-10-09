"""Read-only bounded administrative attention transition history."""
from pathlib import Path
import json,os,stat
from datetime import datetime,timezone,timedelta
PATH=Path('/var/lib/traccar-manager-health/administrative-attention.json')
MAX_BYTES=256*1024
MAX_EVENTS=120

def read_administrative_attention_history(limit=40):
    limit=max(1,min(int(limit),MAX_EVENTS))
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES: raise ValueError('invalid administrative attention history')
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            fst=os.fstat(fd)
            if (fst.st_dev,fst.st_ino)!=(st.st_dev,st.st_ino): raise ValueError('administrative attention history changed')
            with os.fdopen(fd,'r',encoding='utf-8') as f: fd=-1; raw=f.read(MAX_BYTES+1)
        finally:
            if fd>=0: os.close(fd)
        data=json.loads(raw);events=data.get('events',[]) if isinstance(data,dict) else []
        allowed={'state','label','cause','started_at_utc','updated_at_utc','ended_at_utc'}
        safe=[{k:e[k] for k in e if k in allowed} for e in events[-limit:] if isinstance(e,dict) and set(e).issubset(allowed)]
        return {'events':list(reversed(safe)),'count':len(events),'persistent':True,'read_only':True}
    except FileNotFoundError:return {'events':[],'count':0,'persistent':True,'read_only':True}


def _parse(value):
    return datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

def administrative_attention_window(events,hours,now=None):
    now=now or datetime.now(timezone.utc);start=now-timedelta(hours=hours)
    seconds={'NORMAL':0.0,'OBSERVATION':0.0,'ATTENTION':0.0};first=None
    for e in events:
        try:a=_parse(e['started_at_utc']);b=_parse(e['ended_at_utc']) if e.get('ended_at_utc') else now
        except (KeyError,ValueError,TypeError):continue
        if first is None or a<first:first=a
        lo=max(a,start);hi=min(b,now)
        if hi>lo and e.get('state') in seconds:seconds[e['state']]+=(hi-lo).total_seconds()
    covered=sum(seconds.values());window=hours*3600.0
    return {'hours':hours,'coverage_percent':round(covered*100/window,1),'covered_hours':round(covered/3600,2),'state_hours':{k:round(v/3600,2) for k,v in seconds.items()},'complete_window':covered>=window*0.995}


def administrative_attention_trend(events,now=None):
    now=now or datetime.now(timezone.utc)
    # Require six real observed hours before assigning direction.
    baseline=6*3600.0;split=now-timedelta(hours=3);start=now-timedelta(hours=6)
    weights={'NORMAL':0.0,'OBSERVATION':1.0,'ATTENTION':2.0}
    def segment(lo,hi):
        weighted=covered=0.0
        for e in events:
            try:a=_parse(e['started_at_utc']);b=_parse(e['ended_at_utc']) if e.get('ended_at_utc') else now
            except (KeyError,ValueError,TypeError):continue
            left=max(a,lo);right=min(b,hi);sec=max(0.0,(right-left).total_seconds())
            if sec and e.get('state') in weights:covered+=sec;weighted+=sec*weights[e['state']]
        return covered,(weighted/covered if covered else None)
    total,_=segment(start,now)
    if total<baseline*0.995:return {'status':'COLLECTING','label':'Recopilando línea base','observed_hours':round(total/3600,2),'minimum_baseline_hours':6,'direction_delta':None}
    old_cov,old=segment(start,split);new_cov,new=segment(split,now)
    if old_cov<2.9*3600 or new_cov<2.9*3600 or old is None or new is None:return {'status':'COLLECTING','label':'Recopilando línea base','observed_hours':round(total/3600,2),'minimum_baseline_hours':6,'direction_delta':None}
    delta=new-old
    if delta>=0.25:status,label='DETERIORATING','Deteriorándose'
    elif delta<=-0.25:status,label='IMPROVING','Mejorando'
    else:status,label='STABLE','Estable'
    return {'status':status,'label':label,'observed_hours':round(total/3600,2),'minimum_baseline_hours':6,'direction_delta':round(delta,2)}


def administrative_attention_index(events,interventions,now=None):
    now=now or datetime.now(timezone.utc);trend=administrative_attention_trend(events,now)
    current=events[-1].get('state') if events else 'NORMAL';factors=[];score=100
    state_penalty={'NORMAL':0,'OBSERVATION':10,'ATTENTION':25}.get(current,0)
    if state_penalty:score-=state_penalty;factors.append({'code':'current_state','label':'Estado actual '+current.title(),'penalty':state_penalty})
    if trend.get('status')=='DETERIORATING':score-=10;factors.append({'code':'trend','label':'Tendencia deteriorándose','penalty':10})
    elif trend.get('status')=='IMPROVING':factors.append({'code':'trend','label':'Tendencia mejorando','penalty':0})
    elif trend.get('status')=='COLLECTING':factors.append({'code':'trend','label':'Tendencia recopilando línea base','penalty':0})
    stalled=sum(1 for x in interventions if isinstance(x.get('stall'),dict) and x['stall'].get('stalled'))
    stall_penalty=min(30,stalled*15)
    if stall_penalty:score-=stall_penalty;factors.append({'code':'stalled','label':str(stalled)+' intervención'+('' if stalled==1 else 'es')+' estancada'+('' if stalled==1 else 's'),'penalty':stall_penalty})
    recent_failed=0;cutoff=now-timedelta(hours=24)
    for x in interventions:
        if x.get('result_code')!='FAILED':continue
        try:t=_parse(x.get('last_event_at',''))
        except (ValueError,TypeError):continue
        if cutoff<=t<=now:recent_failed+=1
    fail_penalty=min(30,recent_failed*10)
    if fail_penalty:score-=fail_penalty;factors.append({'code':'failed_24h','label':str(recent_failed)+' fallo'+('' if recent_failed==1 else 's')+' en 24 h','penalty':fail_penalty})
    score=max(0,score)
    label='Óptimo' if score>=90 else ('Estable' if score>=75 else ('Atención' if score>=50 else 'Crítico'))
    return {'score':score,'label':label,'factors':factors,'explainable':True,'trend_penalized':trend.get('status')=='DETERIORATING'}

def read_administrative_attention_metrics():
    history=read_administrative_attention_history(MAX_EVENTS);chronological=list(reversed(history['events']))
    from manager.incident_decisions import read_global_interventions
    interventions=read_global_interventions().get('interventions',[])
    return {'windows':{'24h':administrative_attention_window(chronological,24),'7d':administrative_attention_window(chronological,168)},'trend':administrative_attention_trend(chronological),'index':administrative_attention_index(chronological,interventions),'persistent':True,'read_only':True}
