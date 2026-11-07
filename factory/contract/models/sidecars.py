"""Optional, additive review sidecars (contract 0.3)."""

from typing import Literal

from pydantic import BaseModel, Field

Poly = tuple[float, float, float, float, float, float, float, float]


class BlockBox(BaseModel):
    id: str
    cat: str
    ro: int
    part: str | None = None
    poly: Poly
    lang: str | None = None
    parent: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict)
    text: str


class IgnoredRegion(BaseModel):
    poly: Poly


class PageBoxes(BaseModel):
    index: int
    page_id: str
    image_width: int
    image_height: int
    blocks: list[BlockBox]
    ignored: list[IgnoredRegion] = Field(default_factory=list)


class Boxes(BaseModel):
    contract_version: str = "0.3.0"
    doc_id: str
    image_dpi: int
    pages: list[PageBoxes]


class LintFinding(BaseModel):
    rule_id: str
    level: Literal["E", "W"]
    page: int | None = None
    message: str
    block_id: str | None = None


class LintReport(BaseModel):
    contract_version: str = "0.3.0"
    doc_id: str
    findings: list[LintFinding]
