"""Pydantic v2 telemetry data models for BaroGroove AI observability."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TokenUsageMetrics(TelemetryBaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    candidate_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    is_estimated: bool = Field(
        default=False,
        description="True when estimated by deterministic fallback heuristic; False when from Vertex AI usageMetadata.",
    )

    @computed_field
    @property
    def candidates_tokens(self) -> int:
        """Alias for GCP observability and Vertex AI naming compatibility."""
        return self.candidate_tokens

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "candidate_tokens" not in out and "candidates_tokens" in out:
                out["candidate_tokens"] = out["candidates_tokens"]
            if "prompt_tokens" not in out and "promptTokenCount" in out:
                out["prompt_tokens"] = out["promptTokenCount"]
            if "candidate_tokens" not in out and "candidatesTokenCount" in out:
                out["candidate_tokens"] = out["candidatesTokenCount"]
            if "total_tokens" not in out and "totalTokenCount" in out:
                out["total_tokens"] = out["totalTokenCount"]
            if out.get("total_tokens", 0) == 0 and (out.get("prompt_tokens", 0) or out.get("candidate_tokens", 0)):
                out["total_tokens"] = int(out.get("prompt_tokens", 0)) + int(out.get("candidate_tokens", 0))
            return out
        return data

    @classmethod
    def from_vertex_or_estimate(
        cls,
        usage_meta: dict[str, Any] | None,
        *texts: str,
        prompt_text: str = "",
        response_text: str = "",
    ) -> "TokenUsageMetrics":
        if usage_meta and (
            "promptTokenCount" in usage_meta
            or "totalTokenCount" in usage_meta
            or "prompt_tokens" in usage_meta
        ):
            p = int(usage_meta.get("promptTokenCount") or usage_meta.get("prompt_tokens") or 0)
            c = int(
                usage_meta.get("candidatesTokenCount")
                or usage_meta.get("candidate_tokens")
                or usage_meta.get("candidates_tokens")
                or 0
            )
            t = int(usage_meta.get("totalTokenCount") or usage_meta.get("total_tokens") or (p + c))
            return cls(prompt_tokens=p, candidate_tokens=c, total_tokens=t, is_estimated=False)

        if len(texts) >= 3:
            p_str = f"{texts[0]}\n{texts[1]}"
            r_str = str(texts[2])
        elif len(texts) == 2:
            p_str = str(texts[0])
            r_str = str(texts[1])
        elif len(texts) == 1:
            p_str = str(texts[0])
            r_str = response_text
        else:
            p_str = prompt_text
            r_str = response_text

        p_est = max(1, len(str(p_str)) // 4) if p_str else 16
        c_est = max(1, len(str(r_str)) // 4) if r_str else 24
        return cls(
            prompt_tokens=p_est,
            candidate_tokens=c_est,
            total_tokens=p_est + c_est,
            is_estimated=True,
        )


class ToolExecutionStep(TelemetryBaseModel):
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    tool_name: str
    label: str = ""
    detail: str = ""
    status: str = "SUCCESS"
    latency_ms: float = 0.0
    input_args: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    error_message: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_step(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if not out.get("label") and out.get("result_summary"):
                out["label"] = str(out["result_summary"])
            if not out.get("input_args") and isinstance(out.get("arguments"), dict):
                out["input_args"] = out["arguments"]
            return out
        return data

    @computed_field
    @property
    def tool(self) -> str:
        return self.tool_name

    @model_validator(mode="before")
    @classmethod
    def _coerce_tool_step(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "tool_name" not in out and "tool" in out:
                out["tool_name"] = out["tool"]
            if "label" not in out and "tool_name" in out:
                out["label"] = str(out["tool_name"])
            return out
        return data


class TrajectoryRecord(TelemetryBaseModel):
    trajectory_id: str = Field(default_factory=lambda: f"traj_{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    conversation_id: str = ""
    user_id: str = "demo"
    surface: str = Field(default="advisor", description="'advisor', 'dataviz', 'forge', 'a2ui', 'mcp'")
    endpoint: str = Field(default="POST /api/advisor/live")
    created_at: datetime = Field(default_factory=_utc_now)
    latency_ms: float = 0.0
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = Field(default_factory=lambda: f"{uuid.uuid4().int & 0xffffffffffffffff:016x}")
    gcp_trace: str = ""
    requested_model: str = "gemini-2.5-flash"
    execution_path: str = "semantic-fallback"
    http_status: int = 200
    error_state: str | None = None
    token_usage: TokenUsageMetrics = Field(default_factory=TokenUsageMetrics)
    system_instruction: str = ""
    user_prompt: str = ""
    multimodal_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_model_response: str = ""
    parsed_plan: dict[str, Any] = Field(default_factory=dict)
    tool_steps: list[ToolExecutionStep] = Field(default_factory=list)
    extracted_memory_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_gcp_trace(self) -> "TrajectoryRecord":
        if not self.gcp_trace and self.trace_id:
            self.gcp_trace = f"projects/netdev-firebase/traces/{self.trace_id}"
        return self


class SessionRecord(TelemetryBaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    user_id: str = "demo"
    client_surface: str = Field(default="web-flutter", description="'web-flutter', 'a2ui', 'mcp', 'api'")
    started_at: datetime = Field(default_factory=_utc_now)
    last_active_at: datetime = Field(default_factory=_utc_now)
    turn_count: int = 0
    active_geocache_id: str | None = None
    active_theme_id: str | None = None
    active_genre_id: str | None = None
    conversation_ids: list[str] = Field(default_factory=list)
    trajectory_ids: list[str] = Field(default_factory=list)


class ConversationTurn(TelemetryBaseModel):
    turn_id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    turn_index: int = 0
    role: Literal["user", "assistant"] = "user"
    timestamp: datetime = Field(default_factory=_utc_now)
    content: str = ""
    audio_transcript: str | None = None
    spoken_summary: str | None = None
    actions_executed: list[dict[str, Any]] = Field(default_factory=list)
    trajectory_id: str | None = None

    @computed_field
    @property
    def text(self) -> str:
        return self.content

    @model_validator(mode="before")
    @classmethod
    def _coerce_turn(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "content" not in out and "text" in out:
                out["content"] = out["text"]
            return out
        return data


class ConversationRecord(TelemetryBaseModel):
    conversation_id: str = Field(default_factory=lambda: f"conv_{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    user_id: str = "demo"
    surface: str = "advisor"
    title: str = "Atmospheric Session"
    summary: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    turns: list[ConversationTurn] = Field(default_factory=list)


MemoryCategory = Literal[
    "musical_preference",
    "artist_affinity",
    "genre_affinity",
    "weather_mood_association",
    "street_art_landmark",
    "sentiment_like",
    "sentiment_dislike",
]


class MemoryRecord(TelemetryBaseModel):
    memory_id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:12]}")
    user_id: str = "demo"
    conversation_id: str | None = None
    trajectory_id: str | None = None
    source_type: str = "conversation_turn"
    category: str = "musical_preference"
    subject: str = ""
    content: str
    sentiment: str = "positive"
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    last_reinforced_at: datetime = Field(default_factory=_utc_now)
    reinforcement_count: int = 1

    @model_validator(mode="after")
    def _populate_subject(self) -> "MemoryRecord":
        if not self.subject:
            slug = "".join(c if c.isalnum() else "_" for c in self.content.lower()[:36]).strip("_")
            self.subject = f"{self.category}:{slug}"
        return self


class MemoryCreateRequest(TelemetryBaseModel):
    user_id: str = "demo"
    content: str
    category: str = "musical_preference"
    subject: str | None = None
    sentiment: str = "positive"
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    conversation_id: str | None = None
    trajectory_id: str | None = None


class TelemetrySummary(TelemetryBaseModel):
    total_ai_calls: int = 0
    token_usage: dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "candidate_tokens": 0,
            "candidates_tokens": 0,
            "total_tokens": 0,
        }
    )
    active_sessions: int = 0
    total_sessions: int = 0
    total_conversations: int = 0
    stored_memories: int = 0
    avg_latency_ms: float = 0.0
    trajectory_counts_by_surface: dict[str, int] = Field(
        default_factory=lambda: {
            "advisor": 0,
            "dataviz": 0,
            "forge": 0,
            "a2ui": 0,
            "mcp": 0,
        }
    )
    trajectory_counts_by_path: dict[str, int] = Field(
        default_factory=lambda: {
            "vertex-ai": 0,
            "semantic-fallback": 0,
            "deterministic-fallback": 0,
        }
    )
    error_count: int = 0
