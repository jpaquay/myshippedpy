"""W3C / GCP Cloud Trace context propagation & structured observability logging."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .models import TrajectoryRecord

trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("span_id", default=None)


def parse_trace_headers(headers: Any) -> tuple[str, str]:
    """Extract W3C traceparent or GCP X-Cloud-Trace-Context, or generate fresh IDs."""
    # 1. W3C traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
    tp = headers.get("traceparent") if hasattr(headers, "get") else None
    if tp:
        parts = str(tp).strip().split("-")
        if (
            len(parts) >= 4
            and re.fullmatch(r"[0-9a-fA-F]{32}", parts[1])
            and re.fullmatch(r"[0-9a-fA-F]{16}", parts[2])
        ):
            return parts[1].lower(), parts[2].lower()

    # 2. GCP X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE
    gcp = headers.get("x-cloud-trace-context") if hasattr(headers, "get") else None
    if not gcp and hasattr(headers, "get"):
        gcp = headers.get("X-Cloud-Trace-Context")
    if gcp:
        match = re.match(r"([0-9a-fA-F]{32})(?:/([0-9a-fA-F0-9]+))?", str(gcp).strip())
        if match:
            t_id = match.group(1).lower()
            s_raw = match.group(2) or "0000000000000001"
            if s_raw.isdigit():
                s_id = f"{int(s_raw) & 0xffffffffffffffff:016x}"
            elif re.fullmatch(r"[0-9a-fA-F]+", s_raw):
                s_id = s_raw.lower().zfill(16)[:16]
            else:
                s_id = f"{uuid.uuid4().int & 0xffffffffffffffff:016x}"
            return t_id, s_id

    # 3. Generate deterministic-safe fresh W3C/GCP trace & span IDs
    return uuid.uuid4().hex, f"{uuid.uuid4().int & 0xffffffffffffffff:016x}"


def get_current_trace_context() -> tuple[str, str]:
    """Return active (trace_id, span_id) from contextvars or initialize new ones."""
    t_id = trace_id_var.get()
    s_id = span_id_var.get()
    if not t_id or not s_id:
        t_id, s_id = uuid.uuid4().hex, f"{uuid.uuid4().int & 0xffffffffffffffff:016x}"
        trace_id_var.set(t_id)
        span_id_var.set(s_id)
    return t_id, s_id


def get_trace_id() -> str:
    return get_current_trace_context()[0]


def get_span_id() -> str:
    return get_current_trace_context()[1]


def get_gcp_trace(project_id: str = "netdev-firebase") -> str:
    t_id = get_trace_id()
    return f"projects/{project_id or 'netdev-firebase'}/traces/{t_id}"


class TracingMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware propagating W3C/GCP trace context across request lifecycle."""

    async def dispatch(self, request: Request, call_next):
        trace_id, span_id = parse_trace_headers(request.headers)
        t_tok = trace_id_var.set(trace_id)
        s_tok = span_id_var.set(span_id)
        try:
            response = await call_next(request)
            response.headers["X-Cloud-Trace-Context"] = f"{trace_id}/{span_id};o=1"
            response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
            return response
        finally:
            trace_id_var.reset(t_tok)
            span_id_var.reset(s_tok)


class GCPJSONFormatter(logging.Formatter):
    """Formats log records into gcp-antigravity-observability structured JSON."""

    def __init__(self, project_id: str = "netdev-firebase") -> None:
        super().__init__()
        self.project_id = project_id or "netdev-firebase"

    def format(self, record: logging.LogRecord) -> str:
        t_id, s_id = get_current_trace_context()
        rec_t_id = getattr(record, "trace_id", None) or t_id
        rec_s_id = getattr(record, "span_id", None) or s_id
        trace_val = getattr(record, "gcp_trace", None) or f"projects/{self.project_id}/traces/{rec_t_id}"

        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "logging.googleapis.com/trace": trace_val,
            "logging.googleapis.com/spanId": rec_s_id,
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": str(record.lineno),
                "function": record.funcName,
            },
        }
        if hasattr(record, "telemetry"):
            payload["telemetry"] = record.telemetry
        return json.dumps(payload)


def _setup_telemetry_logger() -> logging.Logger:
    logger = logging.getLogger("barogroove.telemetry")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    has_gcp_handler = any(isinstance(getattr(h, "formatter", None), GCPJSONFormatter) for h in logger.handlers)
    if not has_gcp_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(GCPJSONFormatter())
        logger.addHandler(handler)
    return logger


telemetry_logger = _setup_telemetry_logger()


def emit_telemetry_log(record: TrajectoryRecord, message: str | None = None) -> dict[str, Any]:
    """Emit a GCP structured JSON log entry for an AI trajectory and return the payload dict."""
    t_id, s_id = get_current_trace_context()
    trace_id = record.trace_id or t_id
    span_id = record.span_id or s_id
    gcp_trace = record.gcp_trace or f"projects/netdev-firebase/traces/{trace_id}"

    msg = message or f"AI Trajectory recorded: {record.endpoint} ({record.execution_path})"
    telemetry_obj: dict[str, Any] = {
        "trajectory_id": record.trajectory_id,
        "session_id": record.session_id,
        "conversation_id": record.conversation_id,
        "user_id": record.user_id,
        "surface": record.surface,
        "endpoint": record.endpoint,
        "model": record.requested_model,
        "execution_path": record.execution_path,
        "latency_ms": round(record.latency_ms, 2),
        "turn_latency_sec": round(record.latency_ms / 1000.0, 4),
        "token_usage": {
            "prompt_tokens": record.token_usage.prompt_tokens,
            "candidate_tokens": record.token_usage.candidate_tokens,
            "candidates_tokens": record.token_usage.candidate_tokens,
            "total_tokens": record.token_usage.total_tokens,
            "is_estimated": record.token_usage.is_estimated,
        },
        "tool_steps_count": len(record.tool_steps),
        "http_status": record.http_status,
    }
    if record.error_state:
        telemetry_obj["error_state"] = record.error_state

    full_entry: dict[str, Any] = {
        "severity": "ERROR" if record.http_status >= 400 or record.error_state else "INFO",
        "message": msg,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "logging.googleapis.com/trace": gcp_trace,
        "logging.googleapis.com/spanId": span_id,
        "logging.googleapis.com/sourceLocation": {
            "file": "backend/app/telemetry/tracing.py",
            "line": "116",
            "function": "emit_telemetry_log",
        },
        "telemetry": telemetry_obj,
    }

    log_extra = {
        "telemetry": telemetry_obj,
        "gcp_trace": gcp_trace,
        "trace_id": trace_id,
        "span_id": span_id,
    }
    if record.http_status >= 400 or record.error_state:
        telemetry_logger.error(msg, extra=log_extra)
    else:
        telemetry_logger.info(msg, extra=log_extra)

    try:
        from .store import get_telemetry_store

        get_telemetry_store().append_structured_log(full_entry)
    except Exception:
        pass

    return full_entry
