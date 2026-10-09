"""Narrow production deleter for expired Traccar historical logs only."""
from __future__ import annotations
import os,re,stat,hashlib,hmac
from worker.operations.log_retention_boundary_revalidate import revalidate
ROOT='/opt/traccar/logs'; CANARY_ROOT='/var/lib/traccar-manager-retention-canary/logs'; ACTIVE='tracker-server.log'; NAME=re.compile(r'^tracker-server\.log\.\d{8}$')
class ProductionDeleteError(RuntimeError): pass
def _hash_fd(fd:int)->str:
 h=hashlib.sha256()
 while True:
  b=os.read(fd,1024*1024)
  if not b: break
  h.update(b)
 return h.hexdigest()
def delete(names:list[str],retention_days:int,*,root:str=ROOT,evidence_files:list[dict]|None=None,manifest_sha256:str|None=None)->dict[str,object]:
 if root not in (ROOT,CANARY_ROOT): raise ProductionDeleteError('ROOT_DENIED')
 if evidence_files is None or not isinstance(manifest_sha256,str) or len(manifest_sha256)!=64: raise ProductionDeleteError('EVIDENCE_REQUIRED')
 if len(evidence_files)!=len(names): raise ProductionDeleteError('EVIDENCE_MISMATCH')
 evidence={x.get('name'):x for x in evidence_files if isinstance(x,dict) and isinstance(x.get('name'),str)}
 if set(evidence)!=set(names): raise ProductionDeleteError('EVIDENCE_MISMATCH')
 canonical='\n'.join(f"{evidence[n]['name']}|{evidence[n]['size_bytes']}|{evidence[n]['mtime_ns']}|{evidence[n]['device']}|{evidence[n]['inode']}|{evidence[n]['sha256']}" for n in names).encode()
 if not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(),manifest_sha256): raise ProductionDeleteError('MANIFEST_MISMATCH')
 if type(retention_days) is not int or not 30<=retention_days<=3650: raise ProductionDeleteError('INVALID_RETENTION')
 if not isinstance(names,list) or len(names)>3660 or any(not isinstance(n,str) or not NAME.fullmatch(n) or n==ACTIVE for n in names): raise ProductionDeleteError('NAME_DENIED')
 if len(names)!=len(set(names)): raise ProductionDeleteError('DUPLICATE_NAME')
 checks=[revalidate(root,n,retention_days) for n in names]
 if not all(x.eligible for x in checks): raise ProductionDeleteError('REVALIDATION_DENIED')
 dfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); outcomes=[]; validated={}; mutated=False
 try:
  try:
   active_before=os.stat(ACTIVE,dir_fd=dfd,follow_symlinks=False)
   if not stat.S_ISREG(active_before.st_mode): raise ProductionDeleteError('ACTIVE_LOG_NOT_REGULAR')
   active_identity=(active_before.st_dev,active_before.st_ino)
  except FileNotFoundError: raise ProductionDeleteError('ACTIVE_LOG_MISSING')
  for n in names:
   fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=dfd)
   try:
    before=os.fstat(fd)
    if not stat.S_ISREG(before.st_mode): raise ProductionDeleteError('NOT_REGULAR')
    digest=_hash_fd(fd); after_fd=os.fstat(fd)
   finally: os.close(fd)
   expected=evidence[n]; actual=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,digest); wanted=(expected.get('device'),expected.get('inode'),expected.get('size_bytes'),expected.get('mtime_ns'),expected.get('sha256'))
   if actual!=wanted or (after_fd.st_dev,after_fd.st_ino,after_fd.st_size,after_fd.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns): raise ProductionDeleteError('EVIDENCE_CHANGED')
   validated[n]=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
  for n in names:
   before_dev,before_ino,before_size,before_mtime=validated[n]
   after=os.stat(n,dir_fd=dfd,follow_symlinks=False)
   if not stat.S_ISREG(after.st_mode) or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before_dev,before_ino,before_size,before_mtime): raise ProductionDeleteError('IDENTITY_CHANGED')
   os.unlink(n,dir_fd=dfd); mutated=True
   try: os.stat(n,dir_fd=dfd,follow_symlinks=False); raise ProductionDeleteError('POST_DELETE_VERIFY_FAILED')
   except FileNotFoundError: pass
   outcomes.append({'name':n,'outcome':'DELETED_VERIFIED_ABSENT','device':before_dev,'inode':before_ino,'size_bytes':before_size})
  os.fsync(dfd)
  try:
   active=os.stat(ACTIVE,dir_fd=dfd,follow_symlinks=False)
   if not stat.S_ISREG(active.st_mode): raise ProductionDeleteError('ACTIVE_LOG_NOT_REGULAR')
   if (active.st_dev,active.st_ino)!=active_identity: raise ProductionDeleteError('ACTIVE_LOG_IDENTITY_CHANGED')
  except FileNotFoundError: raise ProductionDeleteError('ACTIVE_LOG_MISSING')
 finally:
  if mutated: os.fsync(dfd)
  os.close(dfd)
 return {'status':'EXECUTED','deleted_count':len(outcomes),'deleted_bytes':sum(x['size_bytes'] for x in outcomes),'file_outcomes':outcomes,'post_delete_verified':True,'active_log_protected':True,'production_access':True,'destructive_action_performed':bool(outcomes)}
