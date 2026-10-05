"""Pure PREPARED-stage contract for log retention. Never deletes or mutates files."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib, json
from typing import Callable
from uuid import uuid4
from worker.operations.log_retention_preview import LogRetentionPreview, preview_log_retention

PREPARATION_TTL_SECONDS = 300

class LogRetentionPrepareError(RuntimeError): pass

@dataclass(frozen=True)
class LogRetentionPreparation:
    preparation_id: str
    preview_id: str
    preview_hash: str
    retention_days: int
    candidate_count: int
    candidate_bytes: int
    issued_at_utc: str
    expires_at_utc: str
    one_time_nonce: str
    revalidated: bool = True
    destructive_action_performed: bool = False


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")

def _plan(preview: LogRetentionPreview) -> dict:
    return {"log_dir":preview.log_dir,"retention_days":preview.retention_days,"cutoff_utc":preview.cutoff_utc,
            "candidate_count":preview.candidate_count,"candidate_bytes":preview.candidate_bytes,
            "candidates":[{"name":c.name,"size_bytes":c.size_bytes,"mtime_utc":c.mtime_utc} for c in preview.candidates],
            "active_log_protected":preview.active_log_protected,"destructive_action_performed":preview.destructive_action_performed}

def _hash(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def prepare_log_retention(expected_preview_id: str, *, retention_days: int,
                          preview_provider: Callable[...,LogRetentionPreview]=preview_log_retention,
                          now: datetime|None=None) -> LogRetentionPreparation:
    if not isinstance(expected_preview_id,str) or not expected_preview_id.startswith("preview-") or len(expected_preview_id)!=72:
        raise LogRetentionPrepareError("INVALID_PREVIEW")
    if type(retention_days) is not int or not 30 <= retention_days <= 3650:
        raise LogRetentionPrepareError("INVALID_REQUEST")
    current=preview_provider("/opt/traccar/logs",retention_days=retention_days)
    plan=_plan(current); digest=_hash(plan); current_id="preview-"+digest
    if current.destructive_action_performed is not False or current.active_log_protected is not True:
        raise LogRetentionPrepareError("UNSAFE_PREVIEW")
    if current_id != expected_preview_id:
        raise LogRetentionPrepareError("PREVIEW_STALE")
    issued=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); expires=issued+timedelta(seconds=PREPARATION_TTL_SECONDS)
    nonce="nonce-"+uuid4().hex
    binding={"preview_id":current_id,"preview_hash":digest,"retention_days":retention_days,
             "candidate_count":current.candidate_count,"candidate_bytes":current.candidate_bytes,
             "issued_at_utc":_stamp(issued),"expires_at_utc":_stamp(expires),"one_time_nonce":nonce}
    preparation_id="prepare-"+_hash(binding)
    return LogRetentionPreparation(preparation_id,current_id,digest,retention_days,current.candidate_count,
        current.candidate_bytes,_stamp(issued),_stamp(expires),nonce,True,False)
