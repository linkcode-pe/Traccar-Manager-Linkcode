"""Atomic single-use preparation claims, restricted to sandbox."""
from __future__ import annotations
import hashlib,os,re
ID=re.compile(r'^[A-Za-z0-9._-]{1,128}$')
class ClaimError(RuntimeError):pass
def claim(root:str,preparation_id:str)->str:
 real=os.path.realpath(root)
 if not real.startswith('/tmp/traccar-manager-retention-sandbox/'):raise ClaimError('PRODUCTION_PATH_DENIED')
 if not isinstance(preparation_id,str) or not ID.fullmatch(preparation_id):raise ClaimError('INVALID_PREPARATION_ID')
 d=os.path.join(real,'.claims');os.makedirs(d,mode=0o700,exist_ok=True);name=hashlib.sha256(preparation_id.encode()).hexdigest()+'.claim';path=os.path.join(d,name)
 try:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
 except FileExistsError:raise ClaimError('PREPARATION_ALREADY_CONSUMED') from None
 try:os.write(fd,(preparation_id+'\n').encode());os.fsync(fd)
 finally:os.close(fd)
 return path
