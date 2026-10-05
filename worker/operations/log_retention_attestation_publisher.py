"""Publish immutable PREPARE attestations through a root-owned helper spool."""
from __future__ import annotations
import json,os
from pathlib import Path
from worker.audit.ledger import canonical_json
class AttestationPublishError(RuntimeError):pass
def publish(spool:Path,*,preparation_id:str,binding_hash:str)->None:
 if not preparation_id or len(binding_hash)!=64:raise AttestationPublishError('INVALID_ATTESTATION')
 spool=Path(spool);spool.parent.mkdir(parents=True,exist_ok=True)
 line=canonical_json({'preparation_id':preparation_id,'binding_hash':binding_hash})+b'\n'
 try:
  fd=os.open(spool,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
  try:os.write(fd,line);os.fsync(fd)
  finally:os.close(fd)
 except OSError:raise AttestationPublishError('ATTESTATION_SPOOL_UNAVAILABLE') from None
