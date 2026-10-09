"""Final privileged-boundary filesystem revalidation. Purely read-only."""
from __future__ import annotations
import os,re,stat
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
NAME=re.compile(r'^tracker-server\.log\.(\d{8})$')
@dataclass(frozen=True)
class Revalidation:
 name:str; eligible:bool; reason:str
def revalidate(root:str,name:str,retention_days:int,now:datetime|None=None)->Revalidation:
 if not isinstance(retention_days,int) or retention_days<30 or retention_days>3650:return Revalidation(name,False,'INVALID_RETENTION')
 m=NAME.fullmatch(name) if isinstance(name,str) else None
 if not m:return Revalidation(str(name),False,'NAME_DENIED')
 now=now or datetime.now(timezone.utc)
 try:dated=datetime.strptime(m.group(1),'%Y%m%d').replace(tzinfo=timezone.utc)
 except ValueError:return Revalidation(name,False,'NAME_DENIED')
 if dated >= now-timedelta(days=retention_days):return Revalidation(name,False,'NOT_EXPIRED')
 try:
  fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC))
  try:st=os.fstat(fd)
  finally:os.close(fd)
 except OSError:return Revalidation(name,False,'FS_DENIED')
 if not stat.S_ISREG(st.st_mode):return Revalidation(name,False,'NOT_REGULAR')
 return Revalidation(name,True,'ELIGIBLE')
