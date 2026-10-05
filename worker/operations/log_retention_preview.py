"""Pure preview for Traccar historical-log retention.

This module never deletes, renames, chmods, or creates files.  It deliberately
accepts the log directory and current time as inputs so its policy can be tested
without contacting production.  Execution/deletion belongs to a later,
separately-authorized operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Iterable

DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650
ACTIVE_LOG_NAME = "tracker-server.log"
_HISTORICAL_RE = re.compile(r"^tracker-server\.log\.(\d{8})$")


class PreviewError(ValueError):
    """Fail-closed validation error for a retention preview."""


@dataclass(frozen=True)
class LogCandidate:
    name: str
    path: str
    size_bytes: int
    mtime_utc: str


@dataclass(frozen=True)
class LogRetentionPreview:
    log_dir: str
    retention_days: int
    cutoff_utc: str
    candidate_count: int
    candidate_bytes: int
    candidates: tuple[LogCandidate, ...]
    active_log_protected: bool = True
    destructive_action_performed: bool = False


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def preview_log_retention(
    log_dir: str | Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> LogRetentionPreview:
    """Return the exact historical log candidates without mutating the filesystem."""
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise PreviewError("retention_days must be an integer")
    if not MIN_RETENTION_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise PreviewError("retention_days outside allowed range")

    root = Path(log_dir)
    if not root.is_absolute():
        raise PreviewError("log_dir must be absolute")
    if not root.exists() or not root.is_dir():
        raise PreviewError("log_dir must be an existing directory")
    if root.is_symlink():
        raise PreviewError("log_dir symlink is not allowed")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise PreviewError("now must be timezone-aware")
    cutoff = current.astimezone(timezone.utc) - timedelta(days=retention_days)

    candidates: list[LogCandidate] = []
    for entry in root.iterdir():
        match = _HISTORICAL_RE.fullmatch(entry.name)
        if match is None:
            continue
        if entry.is_symlink() or not entry.is_file():
            continue
        # The filename is allowlisted, and the active unsuffixed log can never match.
        stat_result = entry.stat()
        mtime = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            continue
        candidates.append(LogCandidate(
            name=entry.name,
            path=str(entry),
            size_bytes=stat_result.st_size,
            mtime_utc=_iso_utc(mtime),
        ))

    candidates.sort(key=lambda item: item.name)
    return LogRetentionPreview(
        log_dir=str(root),
        retention_days=retention_days,
        cutoff_utc=_iso_utc(cutoff),
        candidate_count=len(candidates),
        candidate_bytes=sum(item.size_bytes for item in candidates),
        candidates=tuple(candidates),
    )
