"""Deletion helper restricted to an explicitly-created sandbox root.

It is intentionally impossible to point this helper at Traccar production logs.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os,re,stat
from worker.operations.log_retention_preview import LogRetentionPreview,ACTIVE_LOG_NAME

_HIST=re.compile(r'^tracker-server\.log\.\d{8}$')
class SandboxDeleteError(RuntimeError): pass
@dataclass(frozen=True)
class SandboxDeleteResult:
 deleted_count:int; deleted_bytes:int; deleted_names:tuple[str,...]; destructive_action_performed:bool

def delete_preview_candidates_sandbox(preview:LogRetentionPreview,*,sandbox_root:str|Path,_before_unlink=None)->SandboxDeleteResult:
 root=Path(sandbox_root)
 if not isinstance(preview,LogRetentionPreview): raise SandboxDeleteError('INVALID_PREVIEW')
 if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink(): raise SandboxDeleteError('INVALID_SANDBOX')
 resolved=root.resolve(strict=True)
 if str(resolved)=='/opt/traccar/logs' or str(resolved).startswith('/opt/traccar/logs/') or str(resolved).startswith('/opt/traccar/'):
  raise SandboxDeleteError('PRODUCTION_PATH_DENIED')
 if Path(preview.log_dir).resolve(strict=True)!=resolved: raise SandboxDeleteError('PREVIEW_ROOT_MISMATCH')
 names=[c.name for c in preview.candidates]
 if len(names)!=len(set(names)): raise SandboxDeleteError('DUPLICATE_CANDIDATE')
 dfd=os.open(resolved,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 verified=[]
 try:
  # Phase 1: validate EVERY candidate before mutating anything.
  for candidate in preview.candidates:
   if candidate.name==ACTIVE_LOG_NAME or not _HIST.fullmatch(candidate.name) or Path(candidate.path).name!=candidate.name: raise SandboxDeleteError('CANDIDATE_DENIED')
   if Path(candidate.path).parent.resolve(strict=True)!=resolved: raise SandboxDeleteError('PATH_ESCAPE_DENIED')
   try: st=os.stat(candidate.name,dir_fd=dfd,follow_symlinks=False)
   except FileNotFoundError: raise SandboxDeleteError('CANDIDATE_CHANGED') from None
   if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode): raise SandboxDeleteError('CANDIDATE_CHANGED')
   expected_ns=int(__import__('datetime').datetime.fromisoformat(candidate.mtime_utc.replace('Z','+00:00')).timestamp()*1_000_000_000)
   if st.st_size!=candidate.size_bytes or st.st_mtime_ns//1_000_000_000!=expected_ns//1_000_000_000: raise SandboxDeleteError('CANDIDATE_CHANGED')
   verified.append((candidate,st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns//1_000_000_000))
  # Phase 2: re-stat immediately before each unlink. A failure after prior unlinks is explicit PARTIAL_DELETE.
  deleted=[];total=0
  for candidate,dev,ino,size,mtime_s in verified:
   try: current=os.stat(candidate.name,dir_fd=dfd,follow_symlinks=False)
   except FileNotFoundError:
    if deleted: raise SandboxDeleteError('PARTIAL_DELETE') from None
    raise SandboxDeleteError('CANDIDATE_CHANGED') from None
   if not stat.S_ISREG(current.st_mode) or (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns//1_000_000_000)!=(dev,ino,size,mtime_s):
    if deleted: raise SandboxDeleteError('PARTIAL_DELETE')
    raise SandboxDeleteError('CANDIDATE_CHANGED')
   if _before_unlink is not None: _before_unlink(candidate.name,len(deleted),resolved)
   try: os.unlink(candidate.name,dir_fd=dfd)
   except OSError:
    if deleted: raise SandboxDeleteError('PARTIAL_DELETE') from None
    raise SandboxDeleteError('DELETE_FAILED') from None
   deleted.append(candidate.name);total+=size
 finally: os.close(dfd)
 return SandboxDeleteResult(len(deleted),total,tuple(deleted),bool(deleted))
