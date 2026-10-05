"""Fail-closed execution gate for log retention. V1 gate performs NO deletion."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Callable
from worker.operations.log_retention_prepare import LogRetentionPreparation,_hash,_plan
from worker.operations.log_retention_preview import LogRetentionPreview,preview_log_retention
from worker.operations.log_retention_consumption import PreparationConsumptionStore,PreparationConsumptionError

class LogRetentionExecuteError(RuntimeError): pass

@dataclass(frozen=True)
class LogRetentionExecutionGate:
    preparation_id:str; preview_id:str; retention_days:int; candidate_count:int; candidate_bytes:int
    revalidated:bool=True; authorization_consumed:bool=False; destructive_action_performed:bool=False; execution_enabled:bool=False

def _parse(v:str)->datetime:
    try:return datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(timezone.utc)
    except Exception:raise LogRetentionExecuteError('INVALID_PREPARATION') from None

def validate_execution_gate(preparation:LogRetentionPreparation,*,confirmation:str,nonce:str,
                            preview_provider:Callable[...,LogRetentionPreview]=preview_log_retention,
                            now:datetime|None=None, consumption_store:PreparationConsumptionStore|None=None)->LogRetentionExecutionGate:
    if not isinstance(preparation,LogRetentionPreparation) or preparation.revalidated is not True or preparation.destructive_action_performed is not False:raise LogRetentionExecuteError('INVALID_PREPARATION')
    if confirmation!='CONFIRMAR LIMPIEZA':raise LogRetentionExecuteError('CONFIRMATION_REQUIRED')
    if nonce!=preparation.one_time_nonce:raise LogRetentionExecuteError('NONCE_MISMATCH')
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current>=_parse(preparation.expires_at_utc):raise LogRetentionExecuteError('PREPARATION_EXPIRED')
    fresh=preview_provider('/opt/traccar/logs',retention_days=preparation.retention_days); digest=_hash(_plan(fresh))
    if 'preview-'+digest!=preparation.preview_id or digest!=preparation.preview_hash:raise LogRetentionExecuteError('PREVIEW_STALE')
    if fresh.active_log_protected is not True or fresh.destructive_action_performed is not False:raise LogRetentionExecuteError('UNSAFE_PREVIEW')
    consumed=False
    if consumption_store is not None:
        try: consumption_store.consume(preparation); consumed=True
        except PreparationConsumptionError as exc: raise LogRetentionExecuteError(str(exc)) from None
    # Hard feature gate: consumption can be proven one-time, but deletion remains unreachable.
    return LogRetentionExecutionGate(preparation.preparation_id,preparation.preview_id,preparation.retention_days,fresh.candidate_count,fresh.candidate_bytes,authorization_consumed=consumed)
