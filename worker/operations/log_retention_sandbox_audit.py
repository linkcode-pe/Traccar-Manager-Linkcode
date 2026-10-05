"""Durable append-only JSONL audit for sandbox retention executor tests."""
from __future__ import annotations
import hashlib,json,os
from datetime import datetime,timezone
class SandboxAuditError(RuntimeError):pass
def _canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def append_record(path:str,record:dict[str,object])->dict[str,object]:
 if not os.path.realpath(path).startswith('/tmp/traccar-manager-retention-sandbox/'):raise SandboxAuditError('AUDIT_PATH_DENIED')
 os.makedirs(os.path.dirname(path),exist_ok=True)
 previous='0'*64
 if os.path.exists(path):
  with open(path,'rb') as f:
   lines=f.read().splitlines()
  if lines:
   try:previous=json.loads(lines[-1])['record_hash']
   except Exception:raise SandboxAuditError('AUDIT_CORRUPT') from None
 body=dict(record);body['timestamp_utc']=datetime.now(timezone.utc).isoformat();body['previous_hash']=previous;body['record_hash']=hashlib.sha256(_canon(body)).hexdigest()
 fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
 try:os.write(fd,_canon(body)+b'\n');os.fsync(fd)
 finally:os.close(fd)
 return body
