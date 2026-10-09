"""Fixed read-only host metrics for the authenticated Manager dashboard."""
from __future__ import annotations
import os
import json
import time
from pathlib import Path

ROOT = Path('/')
LOG_ROOT = Path('/opt/traccar/logs')
ACTIVE_LOG = 'tracker-server.log'
STORAGE_AUDIT = Path('/run/traccar-manager-storage-audit/storage-audit.json')


def _memory():
    values={}
    with open('/proc/meminfo','r',encoding='ascii') as f:
        for line in f:
            key,_,rest=line.partition(':')
            if key in {'MemTotal','MemAvailable'}:
                values[key]=int(rest.strip().split()[0])*1024
    if set(values)!={'MemTotal','MemAvailable'}: raise OSError('memory unavailable')
    return values['MemTotal'], values['MemTotal']-values['MemAvailable']


def read_server_status():
    fs=os.statvfs(ROOT)
    total=fs.f_blocks*fs.f_frsize; free=fs.f_bavail*fs.f_frsize
    mem_total,mem_used=_memory()
    logs_bytes=0; historical_count=0
    with os.scandir(LOG_ROOT) as entries:
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False): continue
                st=entry.stat(follow_symlinks=False)
            except OSError: continue
            logs_bytes+=st.st_size
            if entry.name.startswith('tracker-server.log.') and entry.name!=ACTIVE_LOG: historical_count+=1
    protection=None
    try:
        st=STORAGE_AUDIT.stat()
        raw=json.loads(STORAGE_AUDIT.read_text('utf-8'))
        fresh=0 <= time.time()-st.st_mtime <= 600
        if fresh and raw.get('schema_version') in {2,3} and isinstance(raw.get('journal'),dict) and isinstance(raw.get('binlogs'),dict) and isinstance(raw.get('database'),dict): protection=raw
    except (OSError,ValueError,TypeError,json.JSONDecodeError): pass
    disk_used=round((total-free)*100/total,1) if total else 0.0
    disk_level='CRITICAL' if disk_used>=90 else ('WARNING' if disk_used>=80 else 'NORMAL')
    policies_ok=bool(protection and protection['journal'].get('status')=='PROTECTED' and protection['binlogs'].get('status')=='PROTECTED')
    storage_health='CRITICAL' if disk_level=='CRITICAL' else ('WARNING' if disk_level=='WARNING' or not policies_ok else 'HEALTHY')
    return {'disk_total_bytes':total,'disk_free_bytes':free,'disk_used_percent':disk_used,'disk_level':disk_level,'storage_health':storage_health,'memory_total_bytes':mem_total,'memory_used_bytes':mem_used,'logs_bytes':logs_bytes,'historical_log_count':historical_count,'storage_protection':protection,'read_only':True}
