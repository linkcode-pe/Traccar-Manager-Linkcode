"""Durable fail-closed anti-replay store for destructive retention authorization."""
from __future__ import annotations
import hashlib,os,fcntl,stat
from pathlib import Path
DEFAULT_PATH=Path('/var/lib/traccar-manager-retention-canary/replay-consumed.sha256')
PRODUCTION_PATH=Path('/var/lib/traccar-manager-retention-canary/production-replay-consumed.sha256')
class ReplayError(RuntimeError):pass
def consume(token:str,*,path:Path=DEFAULT_PATH)->str:
 if not isinstance(token,str) or len(token)!=64: raise ReplayError('INVALID_REPLAY_TOKEN')
 digest=hashlib.sha256(token.encode('ascii')).hexdigest(); path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
 try:
  fd=os.open(path,os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
  try:
   meta=os.fstat(fd)
   if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.geteuid() or (meta.st_mode & 0o077): raise ReplayError('REPLAY_STORE_UNSAFE')
   fcntl.flock(fd,fcntl.LOCK_EX)
   os.lseek(fd,0,os.SEEK_SET)
   with os.fdopen(os.dup(fd),'r',encoding='ascii') as reader:
    if digest in {line.strip() for line in reader if line.strip()}: raise ReplayError('REPLAY_DENIED')
   os.write(fd,(digest+'\n').encode('ascii')); os.fsync(fd)
  finally:
   try: fcntl.flock(fd,fcntl.LOCK_UN)
   finally: os.close(fd)
  dfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
  try: os.fsync(dfd)
  finally: os.close(dfd)
 except ReplayError: raise
 except OSError: raise ReplayError('REPLAY_STORE_UNAVAILABLE') from None
 return digest
