"""trace.json: what happened while generating a document."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class TraceEvent(BaseModel):
    time: datetime
    stage: str
    kind: Literal["stage_start", "stage_end", "llm_call", "tool_call", "check", "retry", "error"]
    page: int | None = None
    provider: str | None = None
    model: str | None = None
    prompt_id: str | None = None  # prompt file + hash, not the full prompt
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    tokens_reasoning: int | None = None
    cost_usd: float | None = None
    detail: dict[str, Any] = {}


class Trace(BaseModel):
    doc_id: str
    factory_version: str
    started: datetime
    finished: datetime | None = None
    status: Literal["ok", "failed"] = "ok"
    events: list[TraceEvent] = []
