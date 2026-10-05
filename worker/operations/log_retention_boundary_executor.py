"""Sandbox-only mutation executor with durable per-file outcome evidence."""
from __future__ import annotations
import os
from worker.operations.log_retention_boundary_revalidate import revalidate
from worker.operations.log_retention_sandbox_audit import append_record
class SandboxExecutionError(RuntimeError):pass
def execute_sandbox(root:str,names:list[str],retention_days:int,*,sandbox_authorized:bool=False,preparation_id:str='sandbox-test',unlink_func=None)->dict[str,object]:
 if not sandbox_authorized:raise SandboxExecutionError('SANDBOX_AUTH_REQUIRED')
 real=os.path.realpath(root)
 if not real.startswith('/tmp/traccar-manager-retention-sandbox/'):raise SandboxExecutionError('PRODUCTION_PATH_DENIED')
 checks=[revalidate(real,n,retention_days) for n in names]
 if not all(x.eligible for x in checks):raise SandboxExecutionError('REVALIDATION_DENIED')
 unlink_func=unlink_func or os.unlink; outcomes=[]; dfd=os.open(real,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 try:
  for n in names:
   try:unlink_func(n,dir_fd=dfd);outcomes.append({'name':n,'outcome':'DELETED'})
   except OSError:outcomes.append({'name':n,'outcome':'FAILED'});break
 finally:os.close(dfd)
 deleted=[x['name'] for x in outcomes if x['outcome']=='DELETED'];failed=[x['name'] for x in outcomes if x['outcome']=='FAILED'];attempted={x['name'] for x in outcomes};not_attempted=[n for n in names if n not in attempted]
 status='SANDBOX_EXECUTED' if not failed and not not_attempted else 'SANDBOX_PARTIAL_FAILURE'
 result={'status':status,'preparation_id':preparation_id,'requested_names':list(names),'revalidated_count':len(checks),'deleted_count':len(deleted),'deleted_names':deleted,'failed_names':failed,'not_attempted_names':not_attempted,'file_outcomes':outcomes,'active_log_included':'tracker-server.log' in names,'production_access':False}
 append_record(os.path.join(real,'execution-audit.jsonl'),result)
 return result
