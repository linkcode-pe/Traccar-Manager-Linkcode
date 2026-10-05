"""Non-destructive privileged-boundary health service. Production access is denied."""
from __future__ import annotations
import json,os,socket
from worker.operations.log_retention_boundary_contract import BoundaryContract
SOCKET_PATH='/run/traccar-manager-retention/boundary.sock'
def response()->bytes:
 d=BoundaryContract().public_status();d.update({'status':'healthy','destructive_action_performed':False});return (json.dumps(d,sort_keys=True,separators=(',',':'))+'\n').encode()
def main():
 try:os.unlink(SOCKET_PATH)
 except FileNotFoundError:pass
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.bind(SOCKET_PATH);os.chmod(SOCKET_PATH,0o666);s.listen(8)
 while True:
  c,_=s.accept()
  with c:
   try:c.recv(1024);c.sendall(response())
   except OSError:pass
if __name__=='__main__':main()
