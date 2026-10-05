"""Read-only host metrics provider over fixed procfs/statvfs interfaces.

This module has no shell, subprocess, database, Traccar, or user-selected path.
The real source is defined but is not invoked by this phase's tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
import re
import time
from typing import Protocol

from api.read_only_dashboard_v1 import ServerMetricsDTO, ValueDTO

METRICS_ERROR_CODES = frozenset({
    "METRICS_PROVIDER_PENDING", "METRICS_SOURCE_NOT_ALLOWED",
    "METRICS_SOURCE_UNAVAILABLE", "METRICS_DATA_INVALID", "METRICS_TIMEOUT",
    "METRICS_INTERNAL_ERROR",
})
_SOURCE_ID = "os.procfs.v1"
_PROC_STAT = "/proc/stat"
_PROC_MEMINFO = "/proc/meminfo"
_MAX_TIMEOUT_SECONDS = 2.0
_CPU_SAMPLE_INTERVAL_SECONDS = 0.1


class MetricsProviderError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in METRICS_ERROR_CODES else "METRICS_INTERNAL_ERROR"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SystemMetricsSample:
    cpu_percent: float
    memory_total_bytes: int
    memory_used_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    observed_at_utc: str

    def __post_init__(self):
        if (type(self.cpu_percent) not in (int, float) or not math.isfinite(self.cpu_percent)
                or not 0 <= self.cpu_percent <= 100):
            raise ValueError("invalid metrics sample")
        for n in (self.memory_total_bytes, self.memory_used_bytes, self.disk_total_bytes, self.disk_free_bytes):
            if type(n) is not int or n < 0:
                raise ValueError("invalid metrics sample")
        if (self.memory_total_bytes <= 0 or self.memory_used_bytes > self.memory_total_bytes
                or self.disk_total_bytes <= 0 or self.disk_free_bytes > self.disk_total_bytes
                or not _valid_utc(self.observed_at_utc)):
            raise ValueError("invalid metrics sample")


def _valid_utc(value: str) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def parse_proc_stat_cpu(text: str) -> tuple[int, int]:
    """Parse only the aggregate first `cpu` line; no host file is opened here."""
    if not isinstance(text, str) or len(text) > 8192:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    lines = text.splitlines()
    if not lines:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    parts = lines[0].split()
    if len(parts) < 5 or parts[0] != "cpu":
        raise MetricsProviderError("METRICS_DATA_INVALID")
    try:
        values = [int(item, 10) for item in parts[1:9]]
    except ValueError:
        raise MetricsProviderError("METRICS_DATA_INVALID") from None
    if len(values) < 4 or any(item < 0 for item in values):
        raise MetricsProviderError("METRICS_DATA_INVALID")
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    if total <= 0 or idle > total:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    return total, idle


def cpu_percent_between(before: tuple[int, int], after: tuple[int, int]) -> float:
    if (not isinstance(before, tuple) or not isinstance(after, tuple)
            or len(before) != 2 or len(after) != 2
            or any(type(v) is not int or v < 0 for v in (*before, *after))):
        raise MetricsProviderError("METRICS_DATA_INVALID")
    delta_total = after[0] - before[0]
    delta_idle = after[1] - before[1]
    if delta_total <= 0 or delta_idle < 0 or delta_idle > delta_total:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    return round((delta_total - delta_idle) * 100.0 / delta_total, 2)


def parse_proc_meminfo(text: str) -> tuple[int, int]:
    """Return total and used bytes from allowlisted MemTotal/MemAvailable only."""
    if not isinstance(text, str) or len(text) > 16384:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    found: dict[str, int] = {}
    for line in text.splitlines():
        if not line.startswith(("MemTotal:", "MemAvailable:")):
            continue
        key, sep, raw = line.partition(":")
        if not sep or key in found:
            raise MetricsProviderError("METRICS_DATA_INVALID")
        parts = raw.split()
        if len(parts) != 2 or parts[1] != "kB" or not re.fullmatch(r"\d+", parts[0]):
            raise MetricsProviderError("METRICS_DATA_INVALID")
        found[key] = int(parts[0], 10) * 1024
    total, available = found.get("MemTotal"), found.get("MemAvailable")
    if total is None or available is None or total <= 0 or available > total:
        raise MetricsProviderError("METRICS_DATA_INVALID")
    return total, total - available


class SystemMetricsSource(Protocol):
    @property
    def provider_id(self) -> str: ...
    def read(self, timeout_seconds: float) -> SystemMetricsSample: ...


class ProcfsSystemMetricsSource:
    """Fixed unprivileged source: aggregate procfs counters and filesystem `/`."""
    provider_id = _SOURCE_ID

    @staticmethod
    def _read_fixed(path: str, limit: int) -> str:
        # Call sites use only the two module constants above; no request path.
        with open(path, "r", encoding="ascii", errors="strict") as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise MetricsProviderError("METRICS_DATA_INVALID")
        return value

    def read(self, timeout_seconds: float) -> SystemMetricsSample:
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0 or timeout_seconds > _MAX_TIMEOUT_SECONDS):
            raise MetricsProviderError("METRICS_TIMEOUT")
        started = time.monotonic()
        try:
            before = parse_proc_stat_cpu(self._read_fixed(_PROC_STAT, 8192))
            time.sleep(_CPU_SAMPLE_INTERVAL_SECONDS)
            after = parse_proc_stat_cpu(self._read_fixed(_PROC_STAT, 8192))
            cpu = cpu_percent_between(before, after)
            mem_total, mem_used = parse_proc_meminfo(self._read_fixed(_PROC_MEMINFO, 16384))
            fs = os.statvfs("/")
            block_size = fs.f_frsize or fs.f_bsize
            disk_total = int(fs.f_blocks) * int(block_size)
            disk_free = int(fs.f_bavail) * int(block_size)
            if block_size <= 0 or disk_total <= 0 or disk_free < 0 or disk_free > disk_total:
                raise MetricsProviderError("METRICS_DATA_INVALID")
            if time.monotonic() - started > timeout_seconds:
                raise MetricsProviderError("METRICS_TIMEOUT")
            observed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            return SystemMetricsSample(cpu, mem_total, mem_used, disk_total, disk_free, observed)
        except MetricsProviderError:
            raise
        except TimeoutError:
            raise MetricsProviderError("METRICS_TIMEOUT") from None
        except OSError:
            raise MetricsProviderError("METRICS_SOURCE_UNAVAILABLE") from None
        except Exception:
            raise MetricsProviderError("METRICS_DATA_INVALID") from None


class SystemMetricsProvider:
    """Maps one trusted metrics source into the dashboard ServerMetricsDTO.

    Invoke only inside the authenticated, audited ReadOnlyDashboardProvider
    execution boundary. This provider has no independent authorization bypass.
    """
    timeout_seconds = _MAX_TIMEOUT_SECONDS

    def __init__(self, source: SystemMetricsSource | None, *, allowed_source_ids: frozenset[str]):
        if not isinstance(allowed_source_ids, frozenset):
            raise ValueError("invalid source allowlist")
        self._source = source
        self._allowed = allowed_source_ids

    def collect(self) -> ServerMetricsDTO:
        if self._source is None:
            raise MetricsProviderError("METRICS_PROVIDER_PENDING")
        source_id = getattr(self._source, "provider_id", None)
        if not isinstance(source_id, str) or source_id not in self._allowed:
            raise MetricsProviderError("METRICS_SOURCE_NOT_ALLOWED")
        try:
            sample = self._source.read(self.timeout_seconds)
        except MetricsProviderError:
            raise
        except TimeoutError:
            raise MetricsProviderError("METRICS_TIMEOUT") from None
        except OSError:
            raise MetricsProviderError("METRICS_SOURCE_UNAVAILABLE") from None
        except Exception:
            raise MetricsProviderError("METRICS_INTERNAL_ERROR") from None
        if not isinstance(sample, SystemMetricsSample):
            raise MetricsProviderError("METRICS_DATA_INVALID")
        try:
            sample.__post_init__()
            return ServerMetricsDTO(
                ValueDTO.available(sample.cpu_percent, sample.observed_at_utc),
                ValueDTO.available(sample.memory_total_bytes, sample.observed_at_utc),
                ValueDTO.available(sample.memory_used_bytes, sample.observed_at_utc),
                ValueDTO.available(sample.disk_total_bytes, sample.observed_at_utc),
                ValueDTO.available(sample.disk_free_bytes, sample.observed_at_utc),
                sample.observed_at_utc,
            )
        except Exception:
            raise MetricsProviderError("METRICS_DATA_INVALID") from None
