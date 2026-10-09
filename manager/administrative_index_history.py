"""Read-only bounded administrative index history."""
from pathlib import Path
import json,os,stat
PATH=Path("/var/lib/traccar-manager-health/administrative-index.json")
MAX_BYTES=256*1024;MAX_EVENTS=120

def read_administrative_index_history(limit=40):
    limit=max(1,min(int(limit),MAX_EVENTS))
    try:
        st=os.lstat(PATH)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_BYTES:raise ValueError("invalid administrative index history")
        fd=os.open(PATH,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            fst=os.fstat(fd)
            if (fst.st_dev,fst.st_ino)!=(st.st_dev,st.st_ino):raise ValueError("administrative index history changed")
            with os.fdopen(fd,"r",encoding="utf-8") as f:fd=-1;raw=f.read(MAX_BYTES+1)
        finally:
            if fd>=0:os.close(fd)
        data=json.loads(raw);events=data.get("events",[]) if isinstance(data,dict) else []
        allowed={"score","label","cause","started_at_utc","updated_at_utc","ended_at_utc"}
        safe=[{k:e[k] for k in e if k in allowed} for e in events[-limit:] if isinstance(e,dict) and set(e).issubset(allowed)]
        return {"events":list(reversed(safe)),"count":len(events),"persistent":True,"read_only":True}
    except FileNotFoundError:return {"events":[],"count":0,"persistent":True,"read_only":True}
