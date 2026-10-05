"""HMAC authentication for immutable retention plans; key supplied by trusted boundary."""
from __future__ import annotations
import hashlib,hmac
from worker.operations.log_retention_plan_fingerprint import fingerprint
class PlanAuthError(ValueError):pass
def sign(key:bytes,preparation_id:str,names:list[str],retention_days:int)->str:
 if not isinstance(key,bytes) or len(key)<32:raise PlanAuthError('WEAK_KEY')
 fp=fingerprint(preparation_id,names,retention_days)
 return hmac.new(key,fp.encode('ascii'),hashlib.sha256).hexdigest()
def verify(key:bytes,token:str,preparation_id:str,names:list[str],retention_days:int)->bool:
 try:expected=sign(key,preparation_id,names,retention_days)
 except Exception:return False
 return isinstance(token,str) and hmac.compare_digest(token,expected)
