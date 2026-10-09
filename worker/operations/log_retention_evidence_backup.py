"""Read-only cryptographic evidence manifest for an approved retention plan."""
from __future__ import annotations
import hashlib, os, re, stat
from datetime import datetime, timezone
ROOT='/opt/traccar/logs'; ACTIVE='tracker-server.log'; NAME=re.compile(r'^tracker-server\.log\.\d{8}$')
class EvidenceBackupError(RuntimeError): pass

def _sha256_fd(fd:int)->str:
 h=hashlib.sha256()
 while True:
  b=os.read(fd,1024*1024)
  if not b: break
  h.update(b)
 return h.hexdigest()

def build(names:list[str])->dict[str,object]:
 if not isinstance(names,list) or len(names)>3660 or any(not isinstance(n,str) or not NAME.fullmatch(n) or n==ACTIVE for n in names):
  raise EvidenceBackupError('NAME_DENIED')
 if len(names)!=len(set(names)): raise EvidenceBackupError('DUPLICATE_NAME')
 dfd=os.open(ROOT,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); files=[]
 try:
  for n in names:
   fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=dfd)
   try:
    before=os.fstat(fd)
    if not stat.S_ISREG(before.st_mode): raise EvidenceBackupError('NOT_REGULAR')
    digest=_sha256_fd(fd)
    after=os.fstat(fd)
   finally: os.close(fd)
   current=os.stat(n,dir_fd=dfd,follow_symlinks=False)
   ident=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
   if ident!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or ident!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns):
    raise EvidenceBackupError('IDENTITY_CHANGED')
   files.append({'name':n,'size_bytes':before.st_size,'mtime_ns':before.st_mtime_ns,'device':before.st_dev,'inode':before.st_ino,'sha256':digest})
 finally: os.close(dfd)
 canonical='\n'.join(f"{x['name']}|{x['size_bytes']}|{x['mtime_ns']}|{x['device']}|{x['inode']}|{x['sha256']}" for x in files).encode()
 return {'status':'EVIDENCE_BACKUP_VERIFIED','backup_kind':'cryptographic-evidence','created_at_utc':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'file_count':len(files),'total_bytes':sum(x['size_bytes'] for x in files),'manifest_sha256':hashlib.sha256(canonical).hexdigest(),'files':files,'content_copied':False,'destructive_action_performed':False}

def verify_manifest(manifest:dict[str,object])->dict[str,object]:
 """Rebuild evidence from disk and require an exact manifest match."""
 if not isinstance(manifest,dict) or manifest.get('status')!='EVIDENCE_BACKUP_VERIFIED' or manifest.get('backup_kind')!='cryptographic-evidence' or manifest.get('content_copied') is not False or manifest.get('destructive_action_performed') is not False:
  raise EvidenceBackupError('MANIFEST_DENIED')
 files=manifest.get('files')
 if not isinstance(files,list) or any(not isinstance(x,dict) or not isinstance(x.get('name'),str) for x in files):
  raise EvidenceBackupError('MANIFEST_DENIED')
 rebuilt=build([x['name'] for x in files])
 if rebuilt['file_count']!=manifest.get('file_count') or rebuilt['total_bytes']!=manifest.get('total_bytes') or rebuilt['manifest_sha256']!=manifest.get('manifest_sha256') or rebuilt['files']!=files:
  raise EvidenceBackupError('EVIDENCE_CHANGED')
 return {'status':'EVIDENCE_REVERIFIED','verified_at_utc':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'file_count':rebuilt['file_count'],'total_bytes':rebuilt['total_bytes'],'manifest_sha256':rebuilt['manifest_sha256'],'identity_match':True,'content_hash_match':True,'destructive_action_performed':False}
