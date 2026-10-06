"""Narrow production deleter for expired Traccar historical logs only."""
from __future__ import annotations
import os,re,stat
from worker.operations.log_retention_boundary_revalidate import revalidate
ROOT='/opt/traccar/logs'; ACTIVE='tracker-server.log'; NAME=re.compile(r'^tracker-server\.log\.\d{8}$')
class ProductionDeleteError(RuntimeError): pass
def delete(names:list[str],retention_days:int)->dict[str,object]:
 if type(retention_days) is not int or not 30<=retention_days<=3650: raise ProductionDeleteError('INVALID_RETENTION')
 if not isinstance(names,list) or len(names)>3660 or any(not isinstance(n,str) or not NAME.fullmatch(n) or n==ACTIVE for n in names): raise ProductionDeleteError('NAME_DENIED')
 if len(names)!=len(set(names)): raise ProductionDeleteError('DUPLICATE_NAME')
 checks=[revalidate(ROOT,n,retention_days) for n in names]
 if not all(x.eligible for x in checks): raise ProductionDeleteError('REVALIDATION_DENIED')
 dfd=os.open(ROOT,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); outcomes=[]
 try:
  for n in names:
   fd=os.open(n,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=dfd)
   try: before=os.fstat(fd)
   finally: os.close(fd)
   if not stat.S_ISREG(before.st_mode): raise ProductionDeleteError('NOT_REGULAR')
   after=os.stat(n,dir_fd=dfd,follow_symlinks=False)
   if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino): raise ProductionDeleteError('IDENTITY_CHANGED')
   os.unlink(n,dir_fd=dfd)
   outcomes.append({'name':n,'outcome':'DELETED','device':before.st_dev,'inode':before.st_ino,'size_bytes':before.st_size})
 finally: os.close(dfd)
 return {'status':'EXECUTED','deleted_count':len(outcomes),'deleted_bytes':sum(x['size_bytes'] for x in outcomes),'file_outcomes':outcomes,'active_log_protected':True,'production_access':True,'destructive_action_performed':bool(outcomes)}
