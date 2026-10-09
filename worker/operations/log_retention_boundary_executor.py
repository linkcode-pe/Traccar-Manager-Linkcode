"""Sandbox-only mutation executor with TOCTOU-resistant inode checks."""
from __future__ import annotations
import os,stat
from worker.operations.log_retention_boundary_revalidate import revalidate
from worker.operations.log_retention_sandbox_audit import append_record
from worker.operations.log_retention_sandbox_claim import claim,ClaimError
from worker.operations.log_retention_plan_fingerprint import fingerprint,verify
class SandboxExecutionError(RuntimeError):pass
def execute_sandbox(root:str,names:list[str],retention_days:int,*,sandbox_authorized:bool=False,preparation_id:str='sandbox-test',plan_fingerprint:str|None=None,before_unlink=None,unlink_func=None)->dict[str,object]:
 if not sandbox_authorized:raise SandboxExecutionError('SANDBOX_AUTH_REQUIRED')
 real=os.path.realpath(root)
 if not real.startswith('/tmp/traccar-manager-retention-sandbox/'):raise SandboxExecutionError('PRODUCTION_PATH_DENIED')
 try:expected=plan_fingerprint or fingerprint(preparation_id,names,retention_days)
 except Exception:raise SandboxExecutionError('PLAN_FINGERPRINT_MISMATCH') from None
 if not verify(expected,preparation_id,names,retention_days):raise SandboxExecutionError('PLAN_FINGERPRINT_MISMATCH')
 try:claim(real,preparation_id)
 except ClaimError as exc:raise SandboxExecutionError(str(exc)) from None
 checks=[revalidate(real,n,retention_days) for n in names]
 if not all(x.eligible for x in checks):raise SandboxExecutionError('REVALIDATION_DENIED')
 unlink_func=unlink_func or os.unlink;outcomes=[];dfd=os.open(real,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 try:
  for n in names:
   try:
    fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=dfd)
    try:before=os.fstat(fd)
    finally:os.close(fd)
    if not stat.S_ISREG(before.st_mode):raise OSError('not regular')
    if before_unlink:before_unlink(n,dfd)
    after=os.stat(n,dir_fd=dfd,follow_symlinks=False)
    if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
     outcomes.append({'name':n,'outcome':'IDENTITY_CHANGED'});break
    unlink_func(n,dir_fd=dfd);outcomes.append({'name':n,'outcome':'DELETED','device':before.st_dev,'inode':before.st_ino})
   except OSError:outcomes.append({'name':n,'outcome':'FAILED'});break
 finally:os.close(dfd)
 deleted=[x['name'] for x in outcomes if x['outcome']=='DELETED'];failed=[x['name'] for x in outcomes if x['outcome'] in ('FAILED','IDENTITY_CHANGED')];attempted={x['name'] for x in outcomes};not_attempted=[n for n in names if n not in attempted];status='SANDBOX_EXECUTED' if not failed and not not_attempted else 'SANDBOX_PARTIAL_FAILURE'
 result={'status':status,'preparation_id':preparation_id,'requested_names':list(names),'revalidated_count':len(checks),'deleted_count':len(deleted),'deleted_names':deleted,'failed_names':failed,'not_attempted_names':not_attempted,'file_outcomes':outcomes,'active_log_included':'tracker-server.log' in names,'production_access':False,'identity_check':'DEVICE_INODE_MATCH_REQUIRED','plan_fingerprint':expected}
 append_record(os.path.join(real,'execution-audit.jsonl'),result);return result
