"""Load HMAC key only from a systemd credential path."""
from __future__ import annotations
import os,stat
class BoundaryCredentialError(RuntimeError):pass
def load_hmac_key()->bytes:
 d=os.environ.get('CREDENTIALS_DIRECTORY')
 if not d or not os.path.isabs(d):raise BoundaryCredentialError('CREDENTIAL_UNAVAILABLE')
 p=os.path.join(d,'retention-plan-hmac.key')
 try:
  st=os.stat(p,follow_symlinks=False)
  if not stat.S_ISREG(st.st_mode):raise BoundaryCredentialError('CREDENTIAL_UNAVAILABLE')
  with open(p,'rb') as f:key=f.read()
 except OSError:raise BoundaryCredentialError('CREDENTIAL_UNAVAILABLE') from None
 if len(key)<32:raise BoundaryCredentialError('CREDENTIAL_INVALID')
 return key
