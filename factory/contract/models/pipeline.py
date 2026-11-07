"""Typed records for generation inputs, design choices, and run accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, RootModel, field_validator


class SourceContent(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    lang: str
    pool_entry: str | None = None
    values: dict[str, Any]


class DesignCriterion(BaseModel):
    options: list[Any] = Field(default_factory=list)
    index: int = 0
    chosen: Any = None
    details: dict[str, Any] = Field(default_factory=dict)
    palette: list[str] = Field(default_factory=list)
    fonts: list[str] = Field(default_factory=list)
    pages: dict[str, str] = Field(default_factory=dict)
    reordered_block_ids: list[str] = Field(default_factory=list)

    @field_validator("details", mode="before")
    @classmethod
    def _details_object(cls, value):
        """A model often writes the rule as a sentence; keep it as {"rule": ...}."""
        if value is None:
            return {}
        return value if isinstance(value, dict) else {"rule": value}

    @field_validator("palette", "fonts", "reordered_block_ids", mode="before")
    @classmethod
    def _as_list(cls, value):
        if value is None:
            return []
        if isinstance(value, dict):  # e.g. {"background": "#fff", "accent": "#123"}
            return [str(item) for item in value.values()]
        return [value] if isinstance(value, str) else value


class DesignSpec(BaseModel):
    direction: dict[str, Any] = Field(default_factory=dict)
    seed: int = 0
    draws: dict[str, list[float]] = Field(default_factory=dict)
    layout: DesignCriterion = Field(default_factory=DesignCriterion)
    style: DesignCriterion = Field(default_factory=DesignCriterion)
    reading_order: DesignCriterion = Field(default_factory=DesignCriterion)
    orientation: DesignCriterion = Field(default_factory=DesignCriterion)
    pages: list[Any] = Field(default_factory=list)
    skipped: list[Any] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)  # code-drawn design parameters
    mode: str = "legacy"
    content_id: str | None = None
    layout_plan: dict[str, Any] = Field(default_factory=dict)
    brief: dict[str, Any] = Field(default_factory=dict)
    table_frame_type: str | None = None
    fingerprint: dict[str, Any] = Field(default_factory=dict)
    thumbnail_paths: list[str] = Field(default_factory=list)


class DocumentRunRecord(BaseModel):
    doc_id: str
    lang: str
    status: str
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_reasoning: int = 0
    cost_usd: float = 0
    seconds: float = 0
    failure_stage: str | None = None


class RunRecord(BaseModel):
    run_id: str
    command: str
    started: datetime
    ended: datetime | None = None
    documents: list[DocumentRunRecord] = Field(default_factory=list)


class ProblemsRecord(BaseModel):
    stage: str
    problems: list[str]


class DocumentIndexEntry(BaseModel):
    doc_id: str
    doc_type: str
    lang: str
    pages: int
    path: str


class DesignLedgerEntry(BaseModel):
    doc_id: str
    doc_type: str
    design_spec: DesignSpec
    content_id: str | None = None
    brief: dict[str, Any] = Field(default_factory=dict)
    fingerprint: dict[str, Any] = Field(default_factory=dict)
    thumbnail_paths: list[str] = Field(default_factory=list)


class LanguageStats(RootModel[dict[str, Any]]):
    """Language report keyed by document type and `_overall`."""


class ExtraStatements(RootModel[dict[str, Any]]):
    """Statement values retained as a bundle sidecar."""
