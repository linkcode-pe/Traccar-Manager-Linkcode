"""Audited RBAC PREPARED-stage flow for maintenance.logs.prepare. Never deletes files."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import hashlib
from typing import Any,Mapping
from uuid import UUID,uuid5
from worker.audit.ledger import AuditLedger,LedgerEvent,canonical_json
from worker.operations.log_retention_preview import preview_log_retention
from worker.operations.log_retention_prepare import prepare_log_retention,LogRetentionPrepareError,_hash,_plan
from worker.operations.log_retention_preparation_store import PreparationStore,PreparationStoreError
from worker.operations.log_retention_execute import validate_execution_gate,LogRetentionExecuteError
from worker.retention_boundary_client import probe_execute_denial,BoundaryUnavailable

OPERATION="maintenance.logs.prepare"; ROLE=OPERATION
TARGET={"type":"traccar-log-directory","id":"/opt/traccar/logs"}
POLICY_ACTOR={"subject_id":"rbac:maintenance.logs.prepare","actor_type":"policy"}
WORKER_ACTOR={"subject_id":"traccar-manager-worker","actor_type":"service"}
_NAMESPACE=UUID("7e7ef680-3975-4bc5-b77b-84af84a2b702")
class MaintenancePrepareError(RuntimeError): pass

def _digest(v:Any)->str:return hashlib.sha256(canonical_json(v)).hexdigest()
def _stamp(v=None)->str:return (v or datetime.now(timezone.utc)).isoformat(timespec="microseconds").replace("+00:00","Z")
def _eid(r,t):return str(uuid5(_NAMESPACE,r+":"+t))
def _event(*,request_id,job_id,subject_id,parameters_hash,event_type,phase,actor,**kw):
 requester={"subject_id":subject_id,"actor_type":"human","roles":[ROLE]}
 return LedgerEvent.create(event_id=_eid(request_id,event_type),timestamp=kw.pop("timestamp",_stamp()),event_type=event_type,phase=phase,request_id=request_id,job_id=job_id,operation=OPERATION,actor=actor,requester=requester,parameters_hash=parameters_hash,target=TARGET,**kw)
def _append(ledger,event,*,authorization=False,prepare=False,result=False):
 try:
  receipt=ledger.append_authorization(event) if authorization else ledger.prepare_execution(event) if prepare else ledger.record_result(event) if result else ledger.append(event)
  if not receipt.durable or not ledger.verify_receipt(receipt):raise MaintenancePrepareError("AUDIT_UNAVAILABLE")
  return receipt
 except MaintenancePrepareError:raise
 except Exception:raise MaintenancePrepareError("AUDIT_UNAVAILABLE") from None

def execute(*,ledger:AuditLedger,request_id:str,subject_id:str,roles:tuple[str,...],preview_id:str,retention_days:int=90,preparation_store:PreparationStore|None=None)->dict[str,Any]:
 if not isinstance(request_id,str) or not request_id or not isinstance(subject_id,str) or not subject_id:raise MaintenancePrepareError("INVALID_REQUEST")
 if not isinstance(roles,tuple) or ROLE not in roles:raise MaintenancePrepareError("FORBIDDEN")
 if not isinstance(preview_id,str) or not preview_id.startswith("preview-") or len(preview_id)!=72 or type(retention_days) is not int or not 30<=retention_days<=3650:raise MaintenancePrepareError("INVALID_REQUEST")
 payload={"preview_id":preview_id,"retention_days":retention_days}; ph=_digest(payload); job_id="job-"+str(uuid5(_NAMESPACE,"job:"+request_id)); requester={"subject_id":subject_id,"actor_type":"human","roles":[ROLE]}
 for et,phase,status in (("REQUEST_RECEIVED","REQUEST","RECEIVED"),("VALIDATION_PASSED","VALIDATION","PASSED"),("PREVIEW_STARTED","PREVIEW","STARTED")):_append(ledger,_event(request_id=request_id,job_id=job_id,subject_id=subject_id,parameters_hash=ph,event_type=et,phase=phase,actor=requester,status=status))
 try: current=preview_log_retention("/opt/traccar/logs",retention_days=retention_days)
 except Exception:raise MaintenancePrepareError("PREPARE_FAILED") from None
 current_hash=_hash(_plan(current)); current_id="preview-"+current_hash
 if current_id!=preview_id:raise MaintenancePrepareError("PREVIEW_STALE")
 try: prep=prepare_log_retention(preview_id,retention_days=retention_days,preview_provider=lambda *_a,**_k:current)
 except LogRetentionPrepareError as exc:raise MaintenancePrepareError(str(exc)) from None
 # The prepare operation's own audited preview is the exact immutable preparation result.
 plan=dict(prep.__dict__); ah=_digest(plan); audit_preview_id="preview-"+ah
 scope={"operation":OPERATION,"target":TARGET,"parameters_hash":ph,"preview_hash":ah}; sh=_digest(scope)
 _append(ledger,_event(request_id=request_id,job_id=job_id,subject_id=subject_id,parameters_hash=ph,event_type="PREVIEW_COMPLETED",phase="PREVIEW",actor=requester,status="COMPLETED",preview_id=audit_preview_id,preview_hash=ah,authorization_scope_hash=sh,metadata={"source_preview_id":preview_id,"preparation_id":prep.preparation_id}))
 issued=datetime.now(timezone.utc); auth_id="auth-"+str(uuid5(_NAMESPACE,"auth:"+request_id)); auth={"authorization_id":auth_id,"requester":requester,"approver":POLICY_ACTOR,"operation":OPERATION,"target":TARGET,"preview_id":audit_preview_id,"preview_hash":ah,"timestamp":_stamp(issued),"expiration":_stamp(issued+timedelta(seconds=60)),"authorization_scope":scope,"parameters_hash":ph,"one_time_nonce":"nonce-"+str(uuid5(_NAMESPACE,auth_id)),"decision":"PENDING","approval_mode":"HUMAN"}
 common=dict(request_id=request_id,job_id=job_id,subject_id=subject_id,parameters_hash=ph,preview_id=audit_preview_id,preview_hash=ah,authorization_id=auth_id,authorization_scope=scope,authorization_scope_hash=sh,approver=POLICY_ACTOR)
 _append(ledger,_event(**common,event_type="AUTHORIZATION_REQUESTED",phase="AUTHORIZATION",actor=requester,status="REQUESTED",authorization=auth),authorization=True)
 granted=dict(auth,decision="GRANTED");_append(ledger,_event(**common,event_type="AUTHORIZATION_GRANTED",phase="AUTHORIZATION",actor=POLICY_ACTOR,status="GRANTED",authorization=granted),authorization=True)
 _append(ledger,_event(**common,event_type="EXECUTION_STARTED",phase="AUDIT_PREPARE",actor=WORKER_ACTOR,status="STARTED",authorization=granted),prepare=True)
 result={"confirmed":True,"outcome":"SUCCEEDED","preparation":plan,"source_preview_id":preview_id,"destructive_action_performed":False}
 _append(ledger,_event(**common,event_type="EXECUTION_COMPLETED",phase="AUDIT_RESULT",actor=WORKER_ACTOR,status="COMPLETED",authorization=granted,result_code="OK",result=result),result=True)
 _append(ledger,_event(**common,event_type="AUDIT_FINALIZED",phase="AUDIT_FINALIZATION",actor=WORKER_ACTOR,status="FINALIZED",authorization=granted,result_code="OK",result=result))
 if not ledger.verify().valid:raise MaintenancePrepareError("AUDIT_UNAVAILABLE")
 readiness="NOT_VERIFIED"
 if preparation_store is not None:
  try:
   preparation_store.issue(prep,subject_id=subject_id)
   preparation_store.verify(prep,subject_id=subject_id)
   gate=validate_execution_gate(prep,confirmation="CONFIRMAR LIMPIEZA",nonce=prep.one_time_nonce,consumption_store=None,consume=False,preview_provider=preview_log_retention)
   if gate.execution_enabled is not False or gate.destructive_action_performed is not False: raise MaintenancePrepareError("UNSAFE_EXECUTION_GATE")
   current_names=[c.name for c in current.candidates]
   if len(current_names)!=prep.candidate_count: raise MaintenancePrepareError("PREVIEW_STALE")
   denial=probe_execute_denial(current_names,retention_days) if current_names else {"status":"DENIED_BY_PRODUCTION_GATE","destructive_action_performed":False,"candidate_count":0}
   if denial.get("status")!="DENIED_BY_PRODUCTION_GATE" or denial.get("destructive_action_performed") is not False or denial.get("candidate_count")!=prep.candidate_count: raise MaintenancePrepareError("UNSAFE_BOUNDARY_GATE")
   readiness="READY_BLOCKED"
  except (PreparationStoreError,LogRetentionExecuteError,BoundaryUnavailable) as exc: raise MaintenancePrepareError(str(exc)) from None
 return {"preparation":plan,"preview_id":preview_id,"audit_preview_id":audit_preview_id,"destructive_action_performed":False,"preparation_stored":preparation_store is not None,"execution_readiness":readiness,"boundary_execute_probe":"DENIED_BY_PRODUCTION_GATE" if readiness=="READY_BLOCKED" else "NOT_VERIFIED","boundary_candidate_count":prep.candidate_count if readiness=="READY_BLOCKED" else None}
