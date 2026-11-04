"""DocIR: the semantic source of a document (CONTRACT.md section 4)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Lang = Literal["vi", "en", "en_vi_mixed"]


class TextSpan(BaseModel):
    type: Literal["text"] = "text"
    text: str


class EquationInlineSpan(BaseModel):
    type: Literal["equation_inline"] = "equation_inline"
    latex: str


class FootnoteMarkSpan(BaseModel):
    type: Literal["footnote_mark"] = "footnote_mark"
    text: str
    target: str | None = None  # block id of the footnote


Span = Annotated[TextSpan | EquationInlineSpan | FootnoteMarkSpan, Field(discriminator="type")]


class TextContent(BaseModel):
    kind: Literal["text"] = "text"
    spans: list[Span]


class TableContent(BaseModel):
    kind: Literal["table"] = "table"
    html: str  # minified <table> ground truth
    header_rows: int = 0  # rows repeated when the table is split across pages


class EquationContent(BaseModel):
    kind: Literal["equation"] = "equation"
    latex: str


class FigureContent(BaseModel):
    kind: Literal["figure"] = "figure"
    asset: str  # path relative to the document folder
    description: str = ""


class ChartContent(BaseModel):
    kind: Literal["chart"] = "chart"
    chart_type: str  # bar, line, donut, waterfall, ...
    data: dict[str, Any]


class MarkContent(BaseModel):
    """Seals, signatures, QR codes, barcodes, checkboxes, form fields."""

    kind: Literal["mark"] = "mark"
    asset: str | None = None
    value: str = ""  # e.g. checkbox state, QR payload, form field value


Content = Annotated[
    TextContent | TableContent | EquationContent | FigureContent | ChartContent | MarkContent,
    Field(discriminator="kind"),
]


class Block(BaseModel):
    id: str
    cat: str  # validated against configs/taxonomy.yaml
    content: Content
    lang: Lang | None = None
    attrs: dict[str, str] = {}
    parent: str | None = None  # e.g. caption -> table/figure
    section: str | None = None  # template-defined grouping, e.g. "B01", "chairman_message"


class DocIR(BaseModel):
    """Blocks in document reading order. Page placement lives in Pagination."""

    doc_id: str
    doc_type: str
    lang: Lang
    blocks: list[Block]
