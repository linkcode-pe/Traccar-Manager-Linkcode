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

def probe_execute_denial(names:list[str],retention_days:int=90)->dict[str,object]:
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(2.0)
 try:s.connect(SOCKET_PATH);s.sendall((json.dumps({'operation':'DELETE_EXPIRED_HISTORICAL_LOGS','names':names,'retention_days':retention_days},sort_keys=True,separators=(',',':'))+'\n').encode());raw=s.recv(4096)
 except OSError:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE') from None
 finally:s.close()
 try:d=json.loads(raw.decode())
 except Exception:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE') from None
 expected={'status':'DENIED_BY_PRODUCTION_GATE','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(names),'revalidated_count':len(names)}
 if d!=expected:raise BoundaryUnavailable('BOUNDARY_UNAVAILABLE')
 return d
