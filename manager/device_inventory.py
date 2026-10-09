"""Read-only sanitized Traccar device inventory from the protected audit snapshot."""
from __future__ import annotations
import json, time
from pathlib import Path

SNAPSHOT=Path('/run/traccar-manager-storage-audit/storage-audit.json')

def read_device_inventory() -> dict:
    st=SNAPSHOT.stat()
    if not 0 <= time.time()-st.st_mtime <= 600: raise OSError('stale device inventory')
    raw=json.loads(SNAPSHOT.read_text('utf-8'))
    devices=((raw.get('database') or {}).get('devices') or {})
    rows=devices.get('inventory')
    if not isinstance(rows,list): raise ValueError('inventory unavailable')
    safe=[]
    for x in rows:
        if not isinstance(x,dict) or set(x)!={'name','enabled','state','last_report_age_seconds','history','imei','contact','expiration','company','category'}: raise ValueError('unsafe inventory schema')
        if x.get('state') not in {'ONLINE','RECENT','INACTIVE','STALE','DISABLED'}: raise ValueError('invalid state')
        h=x.get('history'); allowed={'ONLINE','RECENT','INACTIVE','STALE','DISABLED'}
        if not isinstance(h,dict) or set(h)!={'observations','transitions','recent'} or not isinstance(h.get('recent'),list) or any(not isinstance(e,dict) or set(e)!={'at','state'} or e.get('state') not in allowed for e in h['recent']): raise ValueError('invalid history')
        # Normalize presentation categories from the sanitized device name without
        # mutating Traccar. Legacy deployments use "scooter" for many mototaxis.
        y=dict(x)
        n=str(y.get("name") or "").casefold()
        if "moto taxi" in n or "mototaxi" in n:
            y["category"]="mototaxi"
        elif "cuatrimoto" in n:
            y["category"]="atv"
        elif "minivan" in n:
            y["category"]="van"
        elif "camioneta" in n:
            y["category"]="suv"
        elif "volquete" in n:
            y["category"]="dumptruck"
        safe.append(y)
    return {'observed_at_utc':raw.get('observed_at_utc'),'count':len(safe),'devices':safe,'privacy':{'unique_id_exposed':False,'phone_exposed':False,'position_exposed':False,'coordinates_exposed':False}}
