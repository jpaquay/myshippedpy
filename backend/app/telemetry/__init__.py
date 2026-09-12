"""BaroGroove AI Telemetry, Observability, Session & Memory Subsystem."""

from __future__ import annotations

from .memory_extractor import (
    extract_memories_from_turn,
    extract_memory_from_feedback,
    format_memories_for_prompt,
    format_recent_turns_for_prompt,
)
from .models import (
    ConversationRecord,
    ConversationTurn,
    MemoryCreateRequest,
    MemoryRecord,
    SessionRecord,
    TelemetrySummary,
    TokenUsageMetrics,
    ToolExecutionStep,
    TrajectoryRecord,
)
from .store import DualSinkTelemetryStore, get_telemetry_store, reset_telemetry_store
from .tracing import (
    GCPJSONFormatter,
    TracingMiddleware,
    emit_telemetry_log,
    get_current_trace_context,
    parse_trace_headers,
    trace_id_var,
    span_id_var,
)

__all__ = [
    "ConversationRecord",
    "ConversationTurn",
    "DualSinkTelemetryStore",
    "GCPJSONFormatter",
    "MemoryCreateRequest",
    "MemoryRecord",
    "SessionRecord",
    "TelemetrySummary",
    "TokenUsageMetrics",
    "ToolExecutionStep",
    "TracingMiddleware",
    "TrajectoryRecord",
    "emit_telemetry_log",
    "extract_memories_from_turn",
    "extract_memory_from_feedback",
    "format_memories_for_prompt",
    "format_recent_turns_for_prompt",
    "get_current_trace_context",
    "get_telemetry_store",
    "parse_trace_headers",
    "reset_telemetry_store",
    "span_id_var",
    "trace_id_var",
]
