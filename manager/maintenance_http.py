"""Fail-closed Manager bridge for the read-only log-retention preview."""
from __future__ import annotations
from typing import Any
from manager.auth.session_store import SessionPrincipal
from manager.worker_uds import query_maintenance_logs_preview, WorkerTransportError
from worker.audit.ledger import AuditLedger, SHARED_STATUS_AUDIT_PATH
from worker.maintenance_preview_dispatch import OPERATION, ROLE, TARGET
from manager.worker_uds import MAINTENANCE_ENDPOINT

class MaintenanceAPIError(RuntimeError):
    def __init__(self, code: str): self.code=code; super().__init__(code)

def _ledger():
    return AuditLedger(SHARED_STATUS_AUDIT_PATH, expected_owner_name="traccar-manager-worker",
        expected_group_name="traccar-manager-worker", expected_file_mode=0o640,
        expected_directory_mode=0o750, read_only=True)

class ManagerMaintenanceAPI:
    def __init__(self, *, ledger: Any=None, worker_query=query_maintenance_logs_preview):
        self._ledger=ledger if ledger is not None else _ledger(); self._worker_query=worker_query
    def preview_logs(self, request_id: str, principal: SessionPrincipal, retention_days: int=90) -> dict[str, object]:
        if not isinstance(principal, SessionPrincipal): raise MaintenanceAPIError("API_UNAUTHORIZED")
        if ROLE not in principal.roles: raise MaintenanceAPIError("API_FORBIDDEN")
        try: response=self._worker_query(request_id, principal.subject_id, principal.roles, retention_days)
        except WorkerTransportError as exc:
            if str(exc)=="INVALID_REQUEST": raise MaintenanceAPIError("API_INVALID_REQUEST") from None
            raise MaintenanceAPIError("API_PROVIDER_UNAVAILABLE") from None
        except Exception: raise MaintenanceAPIError("API_PROVIDER_UNAVAILABLE") from None
        if not isinstance(response,dict) or set(response)!={"preview","preview_id","audit_receipt"}:
            raise MaintenanceAPIError("API_PROVIDER_UNAVAILABLE")
        try:
            ok=self._ledger.verify_finalization_receipt_generic(response["audit_receipt"], request_id=request_id,
                subject_id=principal.subject_id, role=ROLE, endpoint=MAINTENANCE_ENDPOINT,
                protocol_operation=OPERATION, operation=OPERATION, target=TARGET)
        except Exception: ok=False
        if ok is not True: raise MaintenanceAPIError("API_AUDIT_UNAVAILABLE")
        return {"schema_version":1,"request_id":request_id,"operation":OPERATION,
                "preview_id":response["preview_id"],"preview":response["preview"]}
    def close(self): return None

# PREPARED bridge is intentionally separate from read-only preview.
from manager.worker_uds import query_maintenance_logs_prepare, MAINTENANCE_PREPARE_ENDPOINT
from worker.maintenance_prepare_dispatch import OPERATION as PREPARE_OPERATION, ROLE as PREPARE_ROLE, TARGET as PREPARE_TARGET

def prepare_logs(self, request_id: str, principal: SessionPrincipal, preview_id: str, retention_days: int=90) -> dict[str, object]:
    if not isinstance(principal,SessionPrincipal): raise MaintenanceAPIError("API_UNAUTHORIZED")
    if PREPARE_ROLE not in principal.roles: raise MaintenanceAPIError("API_FORBIDDEN")
    try: response=query_maintenance_logs_prepare(request_id,principal.subject_id,principal.roles,preview_id,retention_days)
    except WorkerTransportError as exc:
        if str(exc)=="INVALID_REQUEST": raise MaintenanceAPIError("API_INVALID_REQUEST") from None
        raise MaintenanceAPIError("API_PROVIDER_UNAVAILABLE") from None
    try: ok=self._ledger.verify_finalization_receipt_generic(response["audit_receipt"],request_id=request_id,subject_id=principal.subject_id,role=PREPARE_ROLE,endpoint=MAINTENANCE_PREPARE_ENDPOINT,protocol_operation=PREPARE_OPERATION,operation=PREPARE_OPERATION,target=PREPARE_TARGET)
    except Exception: ok=False
    if ok is not True: raise MaintenanceAPIError("API_AUDIT_UNAVAILABLE")
    return {"schema_version":1,"request_id":request_id,"operation":PREPARE_OPERATION,"preview_id":preview_id,"preparation":response["preparation"],"preparation_stored":response.get("preparation_stored") is True,"execution_readiness":response.get("execution_readiness"),"boundary_execute_probe":response.get("boundary_execute_probe"),"boundary_candidate_count":response.get("boundary_candidate_count")}
ManagerMaintenanceAPI.prepare_logs=prepare_logs

from manager.worker_uds import query_retention_boundary_health
def boundary_health(self,request_id:str,principal:SessionPrincipal)->dict[str,object]:
    if not isinstance(principal,SessionPrincipal):raise MaintenanceAPIError('API_UNAUTHORIZED')
    if ROLE not in principal.roles:raise MaintenanceAPIError('API_FORBIDDEN')
    try:b=query_retention_boundary_health(request_id,principal.subject_id,principal.roles)
    except WorkerTransportError as exc:
        if str(exc)=='INVALID_REQUEST':raise MaintenanceAPIError('API_INVALID_REQUEST') from None
        raise MaintenanceAPIError('API_PROVIDER_UNAVAILABLE') from None
    return {'schema_version':1,'request_id':request_id,'boundary':b}
ManagerMaintenanceAPI.boundary_health=boundary_health
