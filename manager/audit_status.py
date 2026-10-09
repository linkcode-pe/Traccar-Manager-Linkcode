"""Bounded sanitized operational audit history for the Manager UI."""
from __future__ import annotations
from collections import deque
from pathlib import Path
import json

AUDIT_PATH=Path('/var/lib/traccar-manager/auth-audit.jsonl')
MAX_BYTES=1024*1024
MAX_EVENTS=40
ALLOWED_EVENTS={'AUTH_LOGIN','AUTH_SESSION_CHECK','AUTH_LOGOUT','AUTH_DASHBOARD_READ'}
ALLOWED_RESULTS={'SUCCEEDED','DENIED','UNAVAILABLE','REQUESTED'}

def read_recent_audit():
    try:
        st=AUDIT_PATH.stat()
        if st.st_size>MAX_BYTES: raise ValueError('audit file too large')
        lines=deque(maxlen=MAX_EVENTS)
        with AUDIT_PATH.open('r',encoding='utf-8') as f:
            for line in f:
                if line.strip(): lines.append(line)
        events=[]
        for line in reversed(lines):
            row=json.loads(line)
            if set(row)!={'timestamp_utc','event','result','reason_code'}: continue
            if row['event'] not in ALLOWED_EVENTS or row['result'] not in ALLOWED_RESULTS: continue
            if not all(isinstance(row[k],str) and len(row[k])<=80 for k in row): continue
            events.append(row)
        return {'events':events,'event_count':len(events),'read_only':True}
    except FileNotFoundError:
        return {'events':[],'event_count':0,'read_only':True}
