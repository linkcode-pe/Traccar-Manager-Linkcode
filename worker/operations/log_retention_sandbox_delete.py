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

def delete_preview_candidates_sandbox(preview:LogRetentionPreview,*,sandbox_root:str|Path)->SandboxDeleteResult:
 root=Path(sandbox_root)
 if not isinstance(preview,LogRetentionPreview): raise SandboxDeleteError('INVALID_PREVIEW')
 if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink(): raise SandboxDeleteError('INVALID_SANDBOX')
 resolved=root.resolve(strict=True)
 # Production paths are a permanent hard deny, independent of caller input.
 if str(resolved)=='/opt/traccar/logs' or str(resolved).startswith('/opt/traccar/logs/') or str(resolved).startswith('/opt/traccar/'):
  raise SandboxDeleteError('PRODUCTION_PATH_DENIED')
 if Path(preview.log_dir).resolve(strict=True)!=resolved: raise SandboxDeleteError('PREVIEW_ROOT_MISMATCH')
 dfd=os.open(resolved,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 deleted=[];total=0
 try:
  for candidate in preview.candidates:
   if candidate.name==ACTIVE_LOG_NAME or not _HIST.fullmatch(candidate.name) or Path(candidate.path).name!=candidate.name: raise SandboxDeleteError('CANDIDATE_DENIED')
   if Path(candidate.path).parent.resolve(strict=True)!=resolved: raise SandboxDeleteError('PATH_ESCAPE_DENIED')
   try: st=os.stat(candidate.name,dir_fd=dfd,follow_symlinks=False)
   except FileNotFoundError: raise SandboxDeleteError('CANDIDATE_CHANGED') from None
   if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode): raise SandboxDeleteError('CANDIDATE_CHANGED')
   expected_ns=int(__import__('datetime').datetime.fromisoformat(candidate.mtime_utc.replace('Z','+00:00')).timestamp()*1_000_000_000)
   # Preview records seconds, so compare size and whole-second mtime; reject any material change.
   if st.st_size!=candidate.size_bytes or st.st_mtime_ns//1_000_000_000!=expected_ns//1_000_000_000: raise SandboxDeleteError('CANDIDATE_CHANGED')
   try: os.unlink(candidate.name,dir_fd=dfd)
   except OSError: raise SandboxDeleteError('DELETE_FAILED') from None
   deleted.append(candidate.name);total+=st.st_size
 finally: os.close(dfd)
 return SandboxDeleteResult(len(deleted),total,tuple(deleted),bool(deleted))
