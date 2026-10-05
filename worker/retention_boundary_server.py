"""Privileged boundary protocol. Production mutation remains hard denied."""
from __future__ import annotations
import json,os,socket
from worker.operations.log_retention_boundary_contract import BoundaryContract,validate_request
from worker.operations.log_retention_boundary_revalidate import revalidate
SOCKET_PATH='/run/traccar-manager-retention/boundary.sock'
def _status():
 d=BoundaryContract().public_status();d.update({'status':'healthy','destructive_action_performed':False});return d
def response()->bytes:
 return (json.dumps(_status(),sort_keys=True,separators=(',',':'))+'\n').encode()
def handle(raw:bytes)->bytes:
 try:
  text=raw.decode().strip()
  if text=='health': out=_status()
  else:
   req=json.loads(text)
   if not isinstance(req,dict) or set(req)!={'operation','names','retention_days'} or not isinstance(req['names'],list) or not validate_request(req['operation'],req['names']): raise ValueError()
   checks=[revalidate('/opt/traccar/logs',n,req['retention_days']) for n in req['names']]
   if not all(x.eligible for x in checks):
    out={'status':'DENIED_BY_REVALIDATION','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':sum(x.eligible for x in checks)}
   else:
    out={'status':'DENIED_BY_PRODUCTION_GATE','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
 except Exception:
  out={'status':'INVALID_REQUEST','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':False}
 return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
def main():
 try:os.unlink(SOCKET_PATH)
 except FileNotFoundError:pass
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.bind(SOCKET_PATH);os.chmod(SOCKET_PATH,0o666);s.listen(8)
 while True:
  c,_=s.accept()
  with c:
   try:c.sendall(handle(c.recv(4096)))
   except OSError:pass
if __name__=='__main__':main()
