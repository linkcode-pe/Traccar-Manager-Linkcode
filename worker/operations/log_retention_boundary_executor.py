"""Sandbox-only mutation executor for retention boundary validation."""
from __future__ import annotations
import os
from worker.operations.log_retention_boundary_revalidate import revalidate
class SandboxExecutionError(RuntimeError):pass
def execute_sandbox(root:str,names:list[str],retention_days:int,*,sandbox_authorized:bool=False)->dict[str,object]:
 if not sandbox_authorized:raise SandboxExecutionError('SANDBOX_AUTH_REQUIRED')
 real=os.path.realpath(root)
 if not real.startswith('/tmp/traccar-manager-retention-sandbox/'):
  raise SandboxExecutionError('PRODUCTION_PATH_DENIED')
 checks=[revalidate(real,n,retention_days) for n in names]
 if not all(x.eligible for x in checks):raise SandboxExecutionError('REVALIDATION_DENIED')
 deleted=[]
 dfd=os.open(real,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 try:
  for n in names:
   os.unlink(n,dir_fd=dfd);deleted.append(n)
 finally:os.close(dfd)
 return {'status':'SANDBOX_EXECUTED','deleted_count':len(deleted),'deleted_names':deleted,'production_access':False}
