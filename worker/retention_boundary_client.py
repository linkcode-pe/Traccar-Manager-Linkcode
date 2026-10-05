"""Strict local client for the DENY_PRODUCTION retention boundary health contract."""
from __future__ import annotations
import json,socket
SOCKET_PATH='/run/traccar-manager-retention/boundary.sock'
EXPECTED={'active_log_denied':True,'allowed_name_pattern':'tracker-server.log.YYYYMMDD','allowed_operation':'DELETE_EXPIRED_HISTORICAL_LOGS','component':'traccar-manager-retention-boundary','destructive_action_performed':False,'mode':'DENY_PRODUCTION','network_access':False,'production_access':False,'separate_identity_required':True,'shell_access':False,'status':'healthy'}
class BoundaryUnavailable(RuntimeError):pass
def query_health()->dict[str,object]:
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(2.0)
 try:s.connect(SOCKET_PATH);s.sendall(b'health\n');raw=s.recv(4096)
 except OSError:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE') from None
 finally:s.close()
 try:d=json.loads(raw.decode())
 except Exception:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE') from None
 if d!=EXPECTED:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE')
 return d

def _request(payload:dict[str,object])->dict[str,object]:
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(2.0)
 try:s.connect(SOCKET_PATH);s.sendall((json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n").encode());raw=s.recv(4096)
 except OSError:raise BoundaryUnavailable("BOUNDARY_UNAVAILABLE") from None
 finally:s.close()
 try:return json.loads(raw.decode())
 except Exception:raise BoundaryUnavailable("BOUNDARY_UNAVAILABLE") from None

def probe_authenticated_denial(*,preparation_id:str,names:list[str],retention_days:int,issued_at_utc:str,expires_at_utc:str,preparation_binding_hash:str)->dict[str,object]:
 import time
 base={"operation":"DELETE_EXPIRED_HISTORICAL_LOGS","preparation_id":preparation_id,"names":names,"retention_days":retention_days,"issued_at_utc":issued_at_utc,"expires_at_utc":expires_at_utc,"preparation_binding_hash":preparation_binding_hash}
 issue=None
 for _ in range(10):
  issue=_request({"action":"ISSUE_AUTH",**base})
  if issue.get("status")=="AUTH_ISSUED":break
  time.sleep(.1)
 if not isinstance(issue,dict) or issue.get("status")!="AUTH_ISSUED" or not isinstance(issue.get("plan_auth"),str):raise BoundaryUnavailable("BOUNDARY_UNAVAILABLE")
 result=_request({"action":"VERIFY",**base,"plan_auth":issue["plan_auth"]})
 expected={"status":"DENIED_BY_PRODUCTION_GATE","mode":"DENY_PRODUCTION","production_access":False,"destructive_action_performed":False,"validated_request":True,"candidate_count":len(names),"revalidated_count":len(names)}
 if result!=expected:raise BoundaryUnavailable("BOUNDARY_UNAVAILABLE")
 return result
