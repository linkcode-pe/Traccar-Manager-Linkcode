"""Durable actor-bound store for issued log-retention preparations."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import fcntl,hashlib,json,os
from worker.audit.ledger import canonical_json
from worker.operations.log_retention_prepare import LogRetentionPreparation
class PreparationStoreError(RuntimeError): pass
class PreparationStore:
 def __init__(self,path:Path): self.path=Path(path)
 def _binding(self,p,subject_id):
  if not isinstance(p,LogRetentionPreparation) or not isinstance(subject_id,str) or not subject_id: raise PreparationStoreError('INVALID_PREPARATION_BINDING')
  body={"subject_id":subject_id,"preparation":asdict(p)}
  return hashlib.sha256(canonical_json(body)).hexdigest()
 def issue(self,p:LogRetentionPreparation,*,subject_id:str):
  digest=self._binding(p,subject_id);self.path.parent.mkdir(parents=True,exist_ok=True)
  try: fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
  except OSError: raise PreparationStoreError('PREPARATION_STORE_UNAVAILABLE') from None
  try:
   fcntl.flock(fd,fcntl.LOCK_EX);os.lseek(fd,0,os.SEEK_SET);raw=os.read(fd,8*1024*1024);records=[]
   if raw:
    try: records=[json.loads(x) for x in raw.decode().splitlines() if x]
    except Exception: raise PreparationStoreError('PREPARATION_STORE_CORRUPT') from None
   for r in records:
    if not isinstance(r,dict) or set(r)!={"preparation_id","subject_id","binding_hash"}: raise PreparationStoreError('PREPARATION_STORE_CORRUPT')
    if r['preparation_id']==p.preparation_id:
     if r['subject_id']==subject_id and r['binding_hash']==digest:return digest
     raise PreparationStoreError('PREPARATION_BINDING_MISMATCH')
   line=canonical_json({"preparation_id":p.preparation_id,"subject_id":subject_id,"binding_hash":digest})+b'\n';os.lseek(fd,0,os.SEEK_END);os.write(fd,line);os.fsync(fd)
  except PreparationStoreError:raise
  except OSError:raise PreparationStoreError('PREPARATION_STORE_UNAVAILABLE') from None
  finally:os.close(fd)
  # Publish a root-owned/shared-readable attestation is handled by deployment boundary; store remains authoritative.
  return digest
 def verify(self,p:LogRetentionPreparation,*,subject_id:str):
  digest=self._binding(p,subject_id)
  try: fd=os.open(self.path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError: raise PreparationStoreError('PREPARATION_NOT_ISSUED') from None
  try:
   fcntl.flock(fd,fcntl.LOCK_SH);raw=os.read(fd,8*1024*1024)
   try: records=[json.loads(x) for x in raw.decode().splitlines() if x]
   except Exception:raise PreparationStoreError('PREPARATION_STORE_CORRUPT') from None
  finally:os.close(fd)
  for r in records:
   if r.get('preparation_id')==p.preparation_id:
    if r.get('subject_id')!=subject_id:raise PreparationStoreError('PREPARATION_ACTOR_MISMATCH')
    if r.get('binding_hash')!=digest:raise PreparationStoreError('PREPARATION_BINDING_MISMATCH')
    return True
  raise PreparationStoreError('PREPARATION_NOT_ISSUED')
