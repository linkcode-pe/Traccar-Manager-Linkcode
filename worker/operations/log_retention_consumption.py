"""Durable one-time preparation consumption for M2 log execution gates."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import fcntl,hashlib,json,os
from worker.audit.ledger import canonical_json
from worker.operations.log_retention_prepare import LogRetentionPreparation

class PreparationConsumptionError(RuntimeError): pass

@dataclass(frozen=True)
class ConsumptionReceipt:
 preparation_id:str; binding_hash:str; consumed:bool=True

class PreparationConsumptionStore:
 def __init__(self,path:Path): self.path=Path(path)
 def consume(self,preparation:LogRetentionPreparation)->ConsumptionReceipt:
  if not isinstance(preparation,LogRetentionPreparation): raise PreparationConsumptionError('INVALID_PREPARATION')
  binding={"preparation_id":preparation.preparation_id,"preview_id":preparation.preview_id,"preview_hash":preparation.preview_hash,"retention_days":preparation.retention_days,"candidate_count":preparation.candidate_count,"candidate_bytes":preparation.candidate_bytes,"issued_at_utc":preparation.issued_at_utc,"expires_at_utc":preparation.expires_at_utc,"one_time_nonce":preparation.one_time_nonce}
  digest=hashlib.sha256(canonical_json(binding)).hexdigest()
  self.path.parent.mkdir(parents=True,exist_ok=True)
  fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_CLOEXEC,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX); os.lseek(fd,0,os.SEEK_SET); raw=os.read(fd,8*1024*1024)
   records=[]
   if raw:
    try: records=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line]
    except Exception: raise PreparationConsumptionError('CONSUMPTION_STORE_CORRUPT') from None
   for record in records:
    if not isinstance(record,dict) or set(record)!={"preparation_id","binding_hash"}: raise PreparationConsumptionError('CONSUMPTION_STORE_CORRUPT')
    if record["preparation_id"]==preparation.preparation_id:
     if record["binding_hash"]!=digest: raise PreparationConsumptionError('PREPARATION_BINDING_MISMATCH')
     raise PreparationConsumptionError('PREPARATION_ALREADY_CONSUMED')
   line=canonical_json({"preparation_id":preparation.preparation_id,"binding_hash":digest})+b'\n'; os.lseek(fd,0,os.SEEK_END)
   view=memoryview(line)
   while view:
    n=os.write(fd,view)
    if n<=0: raise PreparationConsumptionError('CONSUMPTION_STORE_UNAVAILABLE')
    view=view[n:]
   os.fsync(fd)
  except PreparationConsumptionError: raise
  except OSError: raise PreparationConsumptionError('CONSUMPTION_STORE_UNAVAILABLE') from None
  finally: os.close(fd)
  return ConsumptionReceipt(preparation.preparation_id,digest)
