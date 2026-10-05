"""Audited non-destructive dispatch gate for maintenance.logs.execute."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
import hashlib
from typing import Any
from uuid import UUID,uuid5
from worker.audit.ledger import AuditLedger,LedgerEvent,canonical_json
from worker.operations.log_retention_prepare import LogRetentionPreparation
from worker.operations.log_retention_execute import validate_execution_gate,LogRetentionExecuteError
from worker.operations.log_retention_consumption import PreparationConsumptionStore
from worker.operations.log_retention_preparation_store import PreparationStore,PreparationStoreError

OPERATION=ROLE="maintenance.logs.execute"; TARGET={"type":"traccar-log-directory","id":"/opt/traccar/logs"}
POLICY_ACTOR={"subject_id":"rbac:maintenance.logs.execute","actor_type":"policy"}; WORKER_ACTOR={"subject_id":"traccar-manager-worker","actor_type":"service"}
_NAMESPACE=UUID('75c82d7c-e22a-4892-9b44-6e02a0961281')
class MaintenanceExecuteError(RuntimeError):pass
def _d(v):return hashlib.sha256(canonical_json(v)).hexdigest()
def _s(v=None):return (v or datetime.now(timezone.utc)).isoformat(timespec='microseconds').replace('+00:00','Z')
def _event(request_id,job_id,subject_id,parameters_hash,event_type,phase,actor,**kw):return LedgerEvent.create(event_id=str(uuid5(_NAMESPACE,request_id+':'+event_type)),timestamp=kw.pop('timestamp',_s()),event_type=event_type,phase=phase,request_id=request_id,job_id=job_id,operation=OPERATION,actor=actor,requester={"subject_id":subject_id,"actor_type":"human","roles":[ROLE]},parameters_hash=parameters_hash,target=TARGET,**kw)
def _a(ledger,e,kind='append'):
 try:
  receipt=ledger.append_authorization(e) if kind=='auth' else ledger.prepare_execution(e) if kind=='prepare' else ledger.record_result(e) if kind=='result' else ledger.append(e)
  if not receipt.durable or not ledger.verify_receipt(receipt):raise MaintenanceExecuteError('AUDIT_UNAVAILABLE')
  return receipt
 except MaintenanceExecuteError:raise
 except Exception: raise MaintenanceExecuteError('AUDIT_UNAVAILABLE') from None

def execute(*,ledger:AuditLedger,request_id:str,subject_id:str,roles:tuple[str,...],preparation:LogRetentionPreparation,confirmation:str,nonce:str,consumption_store:PreparationConsumptionStore,preparation_store:PreparationStore|None=None,preview_provider=None,now=None)->dict[str,Any]:
 if not isinstance(request_id,str) or not request_id or not isinstance(subject_id,str) or not subject_id:raise MaintenanceExecuteError('INVALID_REQUEST')
 if not isinstance(roles,tuple) or ROLE not in roles:raise MaintenanceExecuteError('FORBIDDEN')
 if preparation_store is not None:
  try: preparation_store.verify(preparation,subject_id=subject_id)
  except PreparationStoreError as exc: raise MaintenanceExecuteError(str(exc)) from None
 nonce_hash=hashlib.sha256(nonce.encode("utf-8")).hexdigest() if isinstance(nonce,str) else "INVALID"
 payload={"preparation":asdict(preparation) if isinstance(preparation,LogRetentionPreparation) else None,"subject_id":subject_id,"confirmation":confirmation,"nonce_hash":nonce_hash};ph=_d(payload);j='job-'+str(uuid5(_NAMESPACE,'job:'+request_id));human={"subject_id":subject_id,"actor_type":"human","roles":[ROLE]}
 for et,phase,status in (("REQUEST_RECEIVED","REQUEST","RECEIVED"),("VALIDATION_PASSED","VALIDATION","PASSED"),("PREVIEW_STARTED","PREVIEW","STARTED")):_a(ledger,_event(request_id,j,subject_id,ph,et,phase,human,status=status))
 kwargs={"confirmation":confirmation,"nonce":nonce,"consumption_store":None,"consume":False}
 if preview_provider is not None:kwargs['preview_provider']=preview_provider
 if now is not None:kwargs['now']=now
 try: gate=validate_execution_gate(preparation,**kwargs)
 except LogRetentionExecuteError as exc:raise MaintenanceExecuteError(str(exc)) from None
 plan=dict(gate.__dict__); preview_hash=_d(plan); preview_id='preview-'+preview_hash;scope={"operation":OPERATION,"target":TARGET,"parameters_hash":ph,"preview_hash":preview_hash};sh=_d(scope)
 _a(ledger,_event(request_id,j,subject_id,ph,"PREVIEW_COMPLETED","PREVIEW",human,status="COMPLETED",preview_id=preview_id,preview_hash=preview_hash,authorization_scope_hash=sh,metadata={}))
 issued=now or datetime.now(timezone.utc);aid='auth-'+str(uuid5(_NAMESPACE,'auth:'+request_id));auth={"authorization_id":aid,"requester":human,"approver":POLICY_ACTOR,"operation":OPERATION,"target":TARGET,"preview_id":preview_id,"preview_hash":preview_hash,"timestamp":_s(issued),"expiration":_s(issued+timedelta(seconds=60)),"authorization_scope":scope,"parameters_hash":ph,"one_time_nonce":"nonce-"+str(uuid5(_NAMESPACE,aid)),"decision":"PENDING","approval_mode":"HUMAN"};common=dict(request_id=request_id,job_id=j,subject_id=subject_id,parameters_hash=ph,preview_id=preview_id,preview_hash=preview_hash,authorization_id=aid,authorization_scope=scope,authorization_scope_hash=sh,approver=POLICY_ACTOR)
 _a(ledger,_event(**common,event_type="AUTHORIZATION_REQUESTED",phase="AUTHORIZATION",actor=human,status="REQUESTED",authorization=auth),kind='auth')
 granted=dict(auth,decision="GRANTED"); _a(ledger,_event(**common,event_type="AUTHORIZATION_GRANTED",phase="AUTHORIZATION",actor=POLICY_ACTOR,status="GRANTED",authorization=granted),kind='auth')
 _a(ledger,_event(**common,event_type="EXECUTION_STARTED",phase="AUDIT_PREPARE",actor=WORKER_ACTOR,status="STARTED",authorization=granted),kind='prepare')
 try:
  consumption_store.consume(preparation)
 except Exception as exc:
  raise MaintenanceExecuteError(str(exc)) from None
 plan["authorization_consumed"]=True
 result={"confirmed":True,"outcome":"BLOCKED_BY_FEATURE_GATE","gate":plan,"destructive_action_performed":False}
 _a(ledger,_event(**common,event_type="EXECUTION_COMPLETED",phase="AUDIT_RESULT",actor=WORKER_ACTOR,status="COMPLETED",authorization=granted,result_code="FEATURE_GATE_BLOCKED",result=result),kind='result')
 _a(ledger,_event(**common,event_type="AUDIT_FINALIZED",phase="AUDIT_FINALIZATION",actor=WORKER_ACTOR,status="FINALIZED",authorization=granted,result_code="FEATURE_GATE_BLOCKED",result=result))
 if not ledger.verify().valid:raise MaintenanceExecuteError('AUDIT_UNAVAILABLE')
 return result
