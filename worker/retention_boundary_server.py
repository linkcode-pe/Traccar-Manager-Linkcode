"""Privileged boundary protocol. Production mutation remains hard denied."""
from __future__ import annotations
import json,os,socket,struct,pwd,hashlib,hmac
from datetime import datetime,timezone
from worker.operations.log_retention_boundary_contract import BoundaryContract,validate_request
from worker.operations.log_retention_boundary_revalidate import revalidate
from worker.operations.log_retention_boundary_credential import load_hmac_key
from worker.operations.log_retention_plan_auth import sign,verify
from worker.operations.log_retention_boundary_replay import consume as consume_replay, ReplayError, PRODUCTION_PATH as PRODUCTION_REPLAY_PATH
from worker.operations.log_retention_production_delete import delete as production_delete, ProductionDeleteError, CANARY_ROOT
from worker.operations.log_retention_evidence_backup import build as build_evidence_backup, EvidenceBackupError
SOCKET_PATH='/run/traccar-manager-retention/boundary.sock'
PREPARATION_ATTESTATION='/var/lib/traccar-manager-retention/preparations.jsonl'
PRODUCTION_DELETE_ENABLED=os.environ.get('TRACCAR_MANAGER_RETENTION_PRODUCTION_DELETE')=='1'
def _status():
 d=BoundaryContract().public_status();d.update({'status':'healthy','destructive_action_performed':False});
 if PRODUCTION_DELETE_ENABLED:d.update({'mode':'PRODUCTION_DELETE_ENABLED','production_access':True})
 return d
def response()->bytes:
 return (json.dumps(_status(),sort_keys=True,separators=(',',':'))+'\n').encode()
def _authorized_peer(c)->bool:
 try:
  _pid,uid,_gid=struct.unpack('3i',c.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
  return uid==pwd.getpwnam('traccar-manager-worker').pw_uid
 except (OSError,KeyError,struct.error):return False
def _attested(preparation_id:str,binding_hash:str,manifest_sha256:str='')->bool:
 try:
  with open(PREPARATION_ATTESTATION,'r',encoding='utf-8') as f:
   for line in f:
    try:r=json.loads(line)
    except Exception:return False
    if r.get('preparation_id')==preparation_id:
     binding_ok=isinstance(binding_hash,str) and hmac.compare_digest(r.get('binding_hash',''),binding_hash)
     if manifest_sha256:
      if binding_ok and isinstance(r.get('manifest_sha256'),str) and hmac.compare_digest(r['manifest_sha256'],manifest_sha256): return True
     elif binding_ok: return True
 except OSError:return False
 return False

def handle(raw:bytes,*,peer_authorized:bool=False)->bytes:
 try:
  text=raw.decode().strip()
  if text=='health': out=_status()
  else:
   req=json.loads(text)
   if isinstance(req,dict) and set(req)=={'operation','names'}:
    if not isinstance(req.get('names'),list) or not validate_request(req.get('operation'),req['names']): raise ValueError()
    out={'status':'DENIED_BY_PRODUCTION_GATE','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(req['names'])}
    return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   if isinstance(req,dict) and set(req)=={'operation','names','retention_days'}:
    if not isinstance(req.get('names'),list) or not validate_request(req.get('operation'),req['names']): raise ValueError()
    checks=[revalidate('/opt/traccar/logs',n,req['retention_days']) for n in req['names']]
    status='DENIED_BY_PRODUCTION_GATE' if all(x.eligible for x in checks) else 'DENIED_BY_REVALIDATION'
    out={'status':status,'mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':sum(x.eligible for x in checks)}
    return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   if req.get('action') in ('ISSUE_AUTH','VERIFY','BACKUP','EXECUTE','CANARY_EXECUTE') and not peer_authorized:
    out={'status':'DENIED_BY_PEER_IDENTITY','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':False};return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   if not isinstance(req,dict) or not isinstance(req.get('names'),list) or not validate_request(req.get('operation'),req['names']): raise ValueError()
   action=req.get('action','VERIFY')
   if action=='ISSUE_AUTH':
    base_keys={'action','operation','preparation_id','names','retention_days','issued_at_utc','expires_at_utc','preparation_binding_hash'}
    execute_keys=base_keys|{'manifest_sha256','evidence_files'}
    if set(req) not in (base_keys,execute_keys):raise ValueError()
    manifest=req.get('manifest_sha256','')
    if manifest and (not isinstance(manifest,str) or len(manifest)!=64 or not isinstance(req.get('evidence_files'),list)):raise ValueError()
    try:
     issued=datetime.fromisoformat(req['issued_at_utc'].replace('Z','+00:00'));expires=datetime.fromisoformat(req['expires_at_utc'].replace('Z','+00:00'));now=datetime.now(timezone.utc)
    except Exception:raise ValueError()
    if issued.tzinfo is None or expires.tzinfo is None or not (issued<=now<expires) or (expires-issued).total_seconds()>300:raise PermissionError('PREPARATION_EXPIRED')
    if not isinstance(req['preparation_binding_hash'],str) or len(req['preparation_binding_hash'])!=64:raise ValueError()
    if not _attested(req['preparation_id'],req['preparation_binding_hash'],manifest):raise PermissionError('PREPARATION_NOT_ATTESTED')
    token=sign(load_hmac_key(),req['preparation_id']+':'+req['preparation_binding_hash']+':'+req['expires_at_utc'],req['names'],req['retention_days'],manifest)
    out={'status':'AUTH_ISSUED','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'plan_auth':token};return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   normal_keys={'action','operation','preparation_id','names','retention_days','issued_at_utc','expires_at_utc','preparation_binding_hash','plan_auth'}
   execute_keys=normal_keys|{'manifest_sha256','evidence_files'}
   if action not in ('VERIFY','BACKUP','EXECUTE','CANARY_EXECUTE') or (action in ('EXECUTE','CANARY_EXECUTE') and set(req)!=execute_keys) or (action not in ('EXECUTE','CANARY_EXECUTE') and set(req)!=normal_keys):raise ValueError()
   try: expires=datetime.fromisoformat(req['expires_at_utc'].replace('Z','+00:00'))
   except Exception:raise ValueError()
   if expires.tzinfo is None or datetime.now(timezone.utc)>=expires:
    out={'status':'DENIED_BY_EXPIRED_PREPARATION','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':False};return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   signed_id=req['preparation_id']+':'+req['preparation_binding_hash']+':'+req['expires_at_utc']
   manifest=req.get('manifest_sha256','')
   if not verify(load_hmac_key(),req['plan_auth'],signed_id,req['names'],req['retention_days'],manifest):
    out={'status':'DENIED_BY_PLAN_AUTH','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':False};return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
   validation_root=CANARY_ROOT if action=='CANARY_EXECUTE' else '/opt/traccar/logs'
   checks=[revalidate(validation_root,n,req['retention_days']) for n in req['names']]
   if not all(x.eligible for x in checks):
    out={'status':'DENIED_BY_REVALIDATION','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':sum(x.eligible for x in checks)}
   elif action=='BACKUP':
    try:
     result=build_evidence_backup(req['names'])
     out={'status':'EVIDENCE_BACKUP_VERIFIED','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks),'backup':result}
    except EvidenceBackupError:
     out={'status':'DENIED_BY_BACKUP_VALIDATION','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
   elif action=='CANARY_EXECUTE':
    try:
     consume_replay(req['plan_auth'])
     result=production_delete(req['names'],req['retention_days'],root=CANARY_ROOT,evidence_files=req['evidence_files'],manifest_sha256=req['manifest_sha256'])
     out={'status':'CANARY_EXECUTED','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':result['destructive_action_performed'],'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks),'deleted_count':result['deleted_count'],'deleted_bytes':result['deleted_bytes'],'post_delete_verified':result.get('post_delete_verified') is True}
    except ReplayError:
     out={'status':'DENIED_BY_REPLAY','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
    except ProductionDeleteError:
     out={'status':'DENIED_BY_CANARY_VALIDATION','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
   elif action=='EXECUTE' and PRODUCTION_DELETE_ENABLED:
    try:
     consume_replay(req['plan_auth'],path=PRODUCTION_REPLAY_PATH)
     result=production_delete(req['names'],req['retention_days'],evidence_files=req['evidence_files'],manifest_sha256=req['manifest_sha256'])
     out={'status':'EXECUTED','mode':'PRODUCTION_DELETE_ENABLED','production_access':True,'destructive_action_performed':result['destructive_action_performed'],'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks),'deleted_count':result['deleted_count'],'deleted_bytes':result['deleted_bytes'],'post_delete_verified':result.get('post_delete_verified') is True}
    except ReplayError:
     out={'status':'DENIED_BY_REPLAY','mode':'PRODUCTION_DELETE_ENABLED','production_access':True,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
    except ProductionDeleteError:
     out={'status':'DENIED_BY_REVALIDATION','mode':'PRODUCTION_DELETE_ENABLED','production_access':True,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
   else:
    out={'status':'DENIED_BY_PRODUCTION_GATE','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':True,'candidate_count':len(req['names']),'revalidated_count':len(checks)}
 except Exception:
  out={'status':'INVALID_REQUEST','mode':'DENY_PRODUCTION','production_access':False,'destructive_action_performed':False,'validated_request':False}
 return (json.dumps(out,sort_keys=True,separators=(',',':'))+'\n').encode()
def main():
 try:os.unlink(SOCKET_PATH)
 except FileNotFoundError:pass
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.bind(SOCKET_PATH);os.chown(SOCKET_PATH,-1,pwd.getpwnam('traccar-manager-worker').pw_gid);os.chmod(SOCKET_PATH,0o660);s.listen(8)
 while True:
  c,_=s.accept()
  with c:
   try:c.sendall(handle(c.recv(4096),peer_authorized=_authorized_peer(c)))
   except OSError:pass
if __name__=='__main__':main()
