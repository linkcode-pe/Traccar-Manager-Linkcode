"""Read-only bounded operational health transition history."""
from pathlib import Path
import json, os, stat
from datetime import datetime, timezone, timedelta
PATH=Path('/var/lib/traccar-manager-health/operational-health.json')
MAX_BYTES=512*1024
MAX_EVENTS=120

def read_operational_health_history(limit=40):
    limit=max(1,min(int(limit),MAX_EVENTS))
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES: raise ValueError('invalid operational health history')
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            fst=os.fstat(fd)
            if (fst.st_dev,fst.st_ino)!=(st.st_dev,st.st_ino): raise ValueError('operational health history changed')
            with os.fdopen(fd,'r',encoding='utf-8') as f: fd=-1; raw=f.read(MAX_BYTES+1)
        finally:
            if fd>=0: os.close(fd)
        data=json.loads(raw); events=data.get('events',[]) if isinstance(data,dict) else []
        allowed={'state','label','cause_code','cause_label','started_at_utc','updated_at_utc','ended_at_utc'}
        safe=[]
        for e in events[-limit:]:
            if isinstance(e,dict) and set(e).issubset(allowed): safe.append({k:e[k] for k in e if k in allowed})
        return {'events':list(reversed(safe)),'count':len(events),'persistent':True,'read_only':True}
    except FileNotFoundError:
        return {'events':[],'count':0,'persistent':True,'read_only':True}


def _parse(value):
    return datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

def operational_availability(events,hours,now=None):
    now=now or datetime.now(timezone.utc); start=now-timedelta(hours=hours)
    seconds={'HEALTHY':0.0,'OBSERVATION':0.0,'ATTENTION':0.0,'CRITICAL':0.0}
    first=None
    for e in events:
        try:
            a=_parse(e['started_at_utc']); b=_parse(e['ended_at_utc']) if e.get('ended_at_utc') else now
        except (KeyError,ValueError,TypeError): continue
        if first is None or a<first:first=a
        lo=max(a,start); hi=min(b,now)
        if hi>lo and e.get('state') in seconds:seconds[e['state']]+=(hi-lo).total_seconds()
    covered=sum(seconds.values()); window=hours*3600.0
    stable=seconds['HEALTHY']+seconds['OBSERVATION']; degraded=seconds['ATTENTION']+seconds['CRITICAL']
    objective=99.9
    budget_seconds=window*(100-objective)/100
    consumed_seconds=degraded
    remaining_seconds=max(0.0,budget_seconds-consumed_seconds)
    complete=covered>=window*0.995
    budget_status='PROVISIONAL' if not complete else ('EXHAUSTED' if consumed_seconds>budget_seconds else 'WITHIN_BUDGET')
    min_baseline=min(window*0.25,6*3600.0)
    if covered<min_baseline:
        forecast_status='COLLECTING'; burn_rate=None; exhaustion_hours=None; projected_consumed=None
    elif consumed_seconds<=0:
        forecast_status='STABLE'; burn_rate=0.0; exhaustion_hours=None; projected_consumed=0.0
    else:
        rate=consumed_seconds/covered
        burn_rate=rate/((100-objective)/100)
        exhaustion_hours=(remaining_seconds/rate/3600.0) if rate>0 and remaining_seconds>0 else 0.0
        projected_consumed=rate*window/60.0
        forecast_status='AT_RISK' if projected_consumed>budget_seconds/60.0 else 'ON_TRACK'
    return {'hours':hours,'coverage_percent':round(covered*100/window,1) if window else 0.0,'covered_hours':round(covered/3600,2),'stable_percent':round(stable*100/covered,2) if covered else None,'degraded_percent':round(degraded*100/covered,2) if covered else None,'state_hours':{k:round(v/3600,2) for k,v in seconds.items()},'complete_window':complete,'slo_target_percent':objective,'error_budget_minutes':round(budget_seconds/60,2),'error_budget_consumed_minutes':round(consumed_seconds/60,2),'error_budget_remaining_minutes':round(remaining_seconds/60,2),'error_budget_status':budget_status,'forecast_status':forecast_status,'burn_rate':round(burn_rate,2) if burn_rate is not None else None,'hours_to_budget_exhaustion':round(exhaustion_hours,2) if exhaustion_hours is not None else None,'projected_consumed_minutes':round(projected_consumed,2) if projected_consumed is not None else None,'forecast_minimum_baseline_hours':round(min_baseline/3600,2)}

def read_operational_availability():
    history=read_operational_health_history(MAX_EVENTS)
    chronological=list(reversed(history['events']))
    return {'windows':{'24h':operational_availability(chronological,24),'7d':operational_availability(chronological,168)},'persistent':True,'read_only':True}
