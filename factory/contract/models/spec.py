"""Base compatibility model and generic document replay inputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_serializer


class BaseSpec(BaseModel):
    doc_id: str
    doc_type: str
    seed: int
    flow: str | None = None  # for document types with several flows, e.g. rigid | creative
    page_count: tuple[int, int]  # inclusive range; the renderer picks the actual count
    lang: str = "vi"
    attributes: dict[str, str] = {}  # requested page/document attributes from quotas
    brief: str = ""  # optional creative brief from the planner
    ro_level: Literal['L0', 'L1', 'L2', 'L3', 'L4'] | None = None
    ro_cases: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def omit_empty_reading_order(self, handler):
        data = handler(self)
        if self.ro_level is None:
            data.pop("ro_level", None)
        if not self.ro_cases:
            data.pop("ro_cases", None)
        return data


class DocSpec(BaseSpec):
    """Seed replay inputs independent of document type."""
    variables: dict[str, object]
    design: Literal["agent", "legacy", "default"] = "agent"
    content_id: str = ""
    design_index: int = 0
    design_seed: int = 0
    batch_id: str = ""
    page_count: tuple[int, int] = (1, 50)
