"""Canonical fingerprint binding an execution authorization to its exact plan."""
from __future__ import annotations
import hashlib,json
class PlanFingerprintError(ValueError):pass
def fingerprint(preparation_id:str,names:list[str],retention_days:int)->str:
 if not isinstance(preparation_id,str) or not preparation_id or len(preparation_id)>128:raise PlanFingerprintError('INVALID_PREPARATION_ID')
 if not isinstance(names,list) or not names or any(not isinstance(n,str) for n in names):raise PlanFingerprintError('INVALID_NAMES')
 if len(names)!=len(set(names)):raise PlanFingerprintError('DUPLICATE_NAMES')
 if not isinstance(retention_days,int) or retention_days<30 or retention_days>3650:raise PlanFingerprintError('INVALID_RETENTION')
 body={'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','preparation_id':preparation_id,'names':names,'retention_days':retention_days}
 raw=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
 return hashlib.sha256(raw).hexdigest()
def verify(expected:str,preparation_id:str,names:list[str],retention_days:int)->bool:
 import hmac
 try:actual=fingerprint(preparation_id,names,retention_days)
 except PlanFingerprintError:return False
 return isinstance(expected,str) and hmac.compare_digest(expected,actual)
