"""Document bundle metadata: pagination and document.json (CONTRACT.md sections 5-6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_serializer

ReadingOrderLevel = Literal['L0', 'L1', 'L2', 'L3', 'L4']


class BlockRef(BaseModel):
    """A block, or one piece of a block split across pages."""

    id: str
    part: int = 1
    parts: int = 1
    row_range: tuple[int, int] | None = None  # tables: body rows [start, end) on this page


class PagePlan(BaseModel):
    index: int  # 1-based
    role: str  # template-defined, e.g. cover, B01, kpi, spread
    blocks: list[BlockRef]  # in page reading order


class Pagination(BaseModel):
    doc_id: str
    pages: list[PagePlan]


class PageEntry(BaseModel):
    page_id: str  # {doc_id}_p{NNN}
    index: int
    file: str  # pages/page_NNN.html
    role: str
    kind: str = "single"  # single | spread
    width_mm: float
    height_mm: float
    ro_level: ReadingOrderLevel | None = None
    ro_cases: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def omit_empty_reading_order(self, handler):
        data = handler(self)
        if self.ro_level is None:
            data.pop("ro_level", None)
        if not self.ro_cases:
            data.pop("ro_cases", None)
        return data


class DocumentManifest(BaseModel):
    """document.json"""

    dataset_version: str = "0.1.0"
    contract_version: str
    taxonomy_version: str
    doc_id: str
    doc_type: str
    flow: str | None = None
    page_count: int
    pages: list[PageEntry]
    attributes: dict[str, str] = {}
    composition: dict = {}  # theme, cover and per-role variants for replay
    image_dpi: int = 200
    provenance: dict[str, str] = {}
    ro_level: ReadingOrderLevel | None = None
    ro_cases: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def omit_empty_reading_order(self, handler):
        data = handler(self)
        if self.ro_level is None:
            data.pop("ro_level", None)
        if not self.ro_cases:
            data.pop("ro_cases", None)
        return data
