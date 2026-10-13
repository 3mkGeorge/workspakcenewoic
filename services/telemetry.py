"""Performance Telemetry & Slow Query Monitoring for StorePro.

Instruments SQLAlchemy engine queries and Flask HTTP request lifecycles to detect
slow queries, track latency percentiles, monitor SQLite engine metrics, and report
process-level resource consumption.
"""

import collections
import ctypes
import re
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from flask import has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Default threshold for what constitutes a slow query in SQLite (ms)
SLOW_QUERY_THRESHOLD_MS = 25.0

# In-memory thread-safe circular buffers
_TELEMETRY_LOCK = threading.Lock()
_SLOW_QUERIES = collections.deque(maxlen=100)
_RECENT_REQUESTS = collections.deque(maxlen=200)

# Aggregate counters
_QUERY_STATS = {
    "total_queries": 0,
    "total_query_time_ms": 0.0,
    "slow_queries": 0,
}

_REQUEST_STATS = {
    "total_requests": 0,
    "total_duration_ms": 0.0,
    "status_2xx": 0,
    "status_3xx": 0,
    "status_4xx": 0,
    "status_5xx": 0,
    "latencies_ms": collections.deque(maxlen=500),
}

_PROCESS_START_TIME = time.time()


def get_process_memory_mb():
    """Retrieve working set (RSS) memory in megabytes on Windows."""
    if sys.platform == "win32":
        try:
            class PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            psapi = ctypes.windll.psapi
            kernel32 = ctypes.windll.kernel32
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return round(pmc.WorkingSetSize / (1024 * 1024), 1)
        except Exception:
            pass
    return 0.0


def get_process_uptime():
    """Return process uptime formatted as string."""
    seconds = int(time.time() - _PROCESS_START_TIME)
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m {secs}s"
    return f"{mins}m {secs}s"


def _sanitize_sql(statement):
    """Strip extraneous whitespace and sensitive strings from SQL statement."""
    return re.sub(r"\s+", " ", statement).strip()


_LISTENERS_REGISTERED = False


def register_telemetry_listeners(engine=None):
    """Attach query timing listeners to SQLAlchemy Engine."""
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return
    _LISTENERS_REGISTERED = True

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if context:
            context._query_start_time = time.perf_counter()

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if not context or not hasattr(context, "_query_start_time"):
            return
        duration_ms = (time.perf_counter() - context._query_start_time) * 1000

        with _TELEMETRY_LOCK:
            _QUERY_STATS["total_queries"] += 1
            _QUERY_STATS["total_query_time_ms"] += duration_ms

            if duration_ms >= SLOW_QUERY_THRESHOLD_MS:
                _QUERY_STATS["slow_queries"] += 1
                sanitized = _sanitize_sql(statement)
                record = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_ms": round(duration_ms, 2),
                    "statement": sanitized[:400] + ("…" if len(sanitized) > 400 else ""),
                    "params_count": len(parameters) if parameters else 0,
                    "path": request.path if has_request_context() else "background",
                }
                _SLOW_QUERIES.append(record)


def record_request_metric(path, method, status_code, duration_ms):
    """Record an HTTP request timing and status metric."""
    with _TELEMETRY_LOCK:
        _REQUEST_STATS["total_requests"] += 1
        _REQUEST_STATS["total_duration_ms"] += duration_ms
        _REQUEST_STATS["latencies_ms"].append(duration_ms)

        if 200 <= status_code < 300:
            _REQUEST_STATS["status_2xx"] += 1
        elif 300 <= status_code < 400:
            _REQUEST_STATS["status_3xx"] += 1
        elif 400 <= status_code < 500:
            _REQUEST_STATS["status_4xx"] += 1
        elif status_code >= 500:
            _REQUEST_STATS["status_5xx"] += 1

        _RECENT_REQUESTS.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 1),
        })


def get_telemetry_snapshot(app, db):
    """Gather full operational performance telemetry for dashboard and reporting."""
    root = Path(app.config.get("ROOT", Path(".")))
    db_path = Path(db.engine.url.database) if hasattr(db.engine.url, "database") and db.engine.url.database else None
    wal_path = Path(str(db_path) + "-wal") if db_path else None

    # SQLite Database metrics
    db_size = db_path.stat().st_size if db_path and db_path.is_file() else 0
    wal_size = wal_path.stat().st_size if wal_path and wal_path.is_file() else 0

    try:
        page_count = db.session.execute(db.text("PRAGMA page_count")).scalar() or 0
        page_size = db.session.execute(db.text("PRAGMA page_size")).scalar() or 4096
        journal_mode = db.session.execute(db.text("PRAGMA journal_mode")).scalar() or "wal"
    except Exception:
        page_count = page_size = 0
        journal_mode = "unknown"

    def _fmt(b):
        if b >= 1024**3:
            return f"{b / (1024**3):.2f} GB"
        if b >= 1024**2:
            return f"{b / (1024**2):.1f} MB"
        if b >= 1024:
            return f"{b / 1024:.0f} KB"
        return f"{b} B"

    with _TELEMETRY_LOCK:
        total_reqs = _REQUEST_STATS["total_requests"]
        avg_req_ms = (_REQUEST_STATS["total_duration_ms"] / total_reqs) if total_reqs else 0.0
        latencies = sorted(list(_REQUEST_STATS["latencies_ms"]))
        p95_ms = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        total_q = _QUERY_STATS["total_queries"]
        avg_q_ms = (_QUERY_STATS["total_query_time_ms"] / total_q) if total_q else 0.0
        slow_q_count = _QUERY_STATS["slow_queries"]
        slow_queries_list = list(_SLOW_QUERIES)[::-1]

        request_stats_copy = dict(_REQUEST_STATS)

    return {
        "system": {
            "uptime": get_process_uptime(),
            "memory_mb": get_process_memory_mb(),
            "threads_count": threading.active_count(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": sys.platform,
        },
        "database": {
            "db_size": _fmt(db_size),
            "db_size_bytes": db_size,
            "wal_size": _fmt(wal_size),
            "wal_size_bytes": wal_size,
            "page_count": page_count,
            "page_size": page_size,
            "journal_mode": journal_mode.upper(),
        },
        "queries": {
            "total_queries": total_q,
            "avg_query_time_ms": round(avg_q_ms, 2),
            "slow_queries_count": slow_q_count,
            "slow_query_threshold_ms": SLOW_QUERY_THRESHOLD_MS,
            "slow_queries": slow_queries_list,
        },
        "requests": {
            "total_requests": total_reqs,
            "avg_duration_ms": round(avg_req_ms, 1),
            "p95_duration_ms": round(p95_ms, 1),
            "status_2xx": request_stats_copy["status_2xx"],
            "status_3xx": request_stats_copy["status_3xx"],
            "status_4xx": request_stats_copy["status_4xx"],
            "status_5xx": request_stats_copy["status_5xx"],
        }
    }
