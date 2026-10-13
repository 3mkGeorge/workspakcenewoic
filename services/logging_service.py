"""Structured Logging Service for StorePro.

Provides JSON-formatted file logging, human-readable console logging,
request correlation IDs, and an in-memory ring buffer for recent log inspection.
"""

import collections
import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import g, has_request_context, request

# In-memory circular buffer for the most recent log events (for admin telemetry UI)
_RECENT_LOGS_LOCK = threading.Lock()
_RECENT_LOGS = collections.deque(maxlen=200)


class StructuredJsonFormatter(logging.Formatter):
    """Outputs log records as machine-readable single-line JSON."""

    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Attach request context if available
        if has_request_context():
            log_obj["req_id"] = getattr(g, "request_id", None)
            log_obj["ip"] = request.remote_addr
            log_obj["method"] = request.method
            log_obj["path"] = request.path
            user = getattr(g, "user", None)
            if user:
                log_obj["user"] = getattr(user, "username", None)
                log_obj["user_id"] = getattr(user, "id", None)

        # Attach custom extra attributes
        for key in ("duration_ms", "status_code", "query_time_ms", "action", "component"):
            if hasattr(record, key):
                log_obj[key] = getattr(record, key)

        return json.dumps(log_obj, ensure_ascii=False)


class StructuredConsoleFormatter(logging.Formatter):
    """Clean, readable console formatter with correlation ID."""

    def format(self, record):
        req_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        asctime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"[{asctime}] [{record.levelname:<5}] [{req_id}]"
        msg = record.getMessage()
        if hasattr(record, "duration_ms"):
            msg += f" ({getattr(record, 'duration_ms'):.1f}ms)"
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{prefix} {msg}"


class MemoryBufferHandler(logging.Handler):
    """Captures recent log events into a thread-safe circular buffer."""

    def emit(self, record):
        try:
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "req_id": getattr(g, "request_id", "-") if has_request_context() else "-",
            }
            with _RECENT_LOGS_LOCK:
                _RECENT_LOGS.append(entry)
        except Exception:
            self.handleError(record)


def get_recent_logs(limit=50, level=None):
    """Retrieve recent log events for admin telemetry."""
    with _RECENT_LOGS_LOCK:
        logs = list(_RECENT_LOGS)
    if level:
        level_upper = level.upper()
        logs = [e for e in logs if e["level"] == level_upper]
    return logs[-limit:][::-1]


def init_structured_logging(app):
    """Initialize structured logging handlers on the Flask app."""
    root_dir = Path(app.config.get("ROOT", Path(".")))
    logs_dir = root_dir / "instance" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Clean existing custom handlers to prevent duplication
    app_logger = app.logger
    app_logger.setLevel(logging.INFO)

    # 1. Human-readable rotating log file
    text_log_path = logs_dir / "storepro.log"
    text_handler = RotatingFileHandler(
        text_log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    text_handler.setFormatter(StructuredConsoleFormatter())
    text_handler.setLevel(logging.INFO)

    # 2. JSON structured rotating log file
    json_log_path = logs_dir / "storepro.json.log"
    json_handler = RotatingFileHandler(
        json_log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    json_handler.setFormatter(StructuredJsonFormatter())
    json_handler.setLevel(logging.INFO)

    # 3. Memory buffer handler
    mem_handler = MemoryBufferHandler()
    mem_handler.setLevel(logging.INFO)

    # Clean existing custom handlers to prevent stale paths across test runs or reloads
    for h in list(app_logger.handlers):
        if isinstance(h, (RotatingFileHandler, MemoryBufferHandler)):
            try:
                h.flush()
                h.close()
            except Exception:
                pass
            app_logger.removeHandler(h)

    app_logger.addHandler(text_handler)
    app_logger.addHandler(json_handler)
    app_logger.addHandler(mem_handler)

    app_logger.info("Structured logging initialized (text and JSON destinations active).")
    try:
        text_handler.flush()
        json_handler.flush()
    except Exception:
        pass
    return app_logger


def shutdown_structured_logging(app):
    """Close and remove logging handlers to release file descriptors (essential on Windows)."""
    app_logger = getattr(app, "logger", None)
    if not app_logger:
        return
    for h in list(app_logger.handlers):
        if isinstance(h, (RotatingFileHandler, MemoryBufferHandler)):
            try:
                h.flush()
                h.close()
            except Exception:
                pass
            app_logger.removeHandler(h)

