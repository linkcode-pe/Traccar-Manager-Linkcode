"""Bounded read-only preventive incident history."""
from __future__ import annotations
from pathlib import Path
import json, os, stat
PATH=Path('/var/lib/traccar-manager-health/incidents.json')
MAX_BYTES=512*1024
MAX_EVENTS=100

def read_incidents(limit=30):
    limit=max(1,min(int(limit),MAX_EVENTS))
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES:
            raise ValueError('invalid incident store')
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            fst=os.fstat(fd)
            if fst.st_dev!=st.st_dev or fst.st_ino!=st.st_ino:
                raise ValueError('incident store changed')
            with os.fdopen(fd,'r',encoding='utf-8') as f:
                fd=-1
                raw=f.read(MAX_BYTES+1)
        finally:
            if fd>=0: os.close(fd)
        data=json.loads(raw)
        events=data.get('events',[]) if isinstance(data,dict) else []
        allowed={'id','kind','component','severity','status','opened_at_utc','updated_at_utc','resolved_at_utc','summary','detail','operational_priority'}
        safe=[]
        for e in events[-limit:]:
            if isinstance(e,dict) and set(e).issubset(allowed):
                safe.append({k:e[k] for k in e if k in allowed})
        return {'events':list(reversed(safe)),'count':len(events),'persistent':True,'read_only':True}
    except FileNotFoundError:
        return {'events':[],'count':0,'persistent':True,'read_only':True}
