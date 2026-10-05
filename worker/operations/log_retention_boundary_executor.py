"""Sandbox-only mutation executor for retention boundary validation."""
from __future__ import annotations
import os
from worker.operations.log_retention_boundary_revalidate import revalidate
from worker.operations.log_retention_sandbox_audit import append_record
class SandboxExecutionError(RuntimeError):pass
def execute_sandbox(root:str,names:list[str],retention_days:int,*,sandbox_authorized:bool=False,preparation_id:str="sandbox-test")->dict[str,object]:
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
 result={'status':'SANDBOX_EXECUTED','preparation_id':preparation_id,'requested_names':list(names),'revalidated_count':len(checks),'deleted_count':len(deleted),'deleted_names':deleted,'active_log_included':'tracker-server.log' in names,'production_access':False};append_record(os.path.join(real,'execution-audit.jsonl'),result);return result
