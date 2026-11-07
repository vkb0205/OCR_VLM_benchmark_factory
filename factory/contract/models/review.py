"""Versioned review data, separate from immutable document bundles."""
from typing import Literal
from pydantic import BaseModel, Field

Verdict = Literal['correct','box_off','text_wrong','wrong_category','wrong_order','should_ignore']
Decision = Literal['approved','flagged','rejected']

class Correction(BaseModel):
    poly: tuple[float,float,float,float,float,float,float,float] | None = None
    cat: str | None = None
    attrs: dict[str,str] | None = None

class BlockReview(BaseModel):
    fix: Correction | None = None
    verdict: Verdict
    note: str = ''
    by: str
    at: str

class PageReview(BaseModel):
    order: list[str] | None = None
    version: int = 0
    decision: Decision | None = None
    note: str = ''
    by: str = ''
    at: str = ''
    blocks: dict[str, BlockReview] = Field(default_factory=dict)

class Review(BaseModel):
    review_version: str = '0.1.0'
    subset: str
    doc_id: str
    bundle_hash: str
    status: str = 'todo'
    pages: dict[str, PageReview] = Field(default_factory=dict)
    history: list[dict] = Field(default_factory=list)

class VerdictWrite(BaseModel):
    fix: Correction | None = None
    version: int
    reviewer: str = Field(min_length=1)
    verdict: Verdict
    note: str = ''

class DecisionWrite(BaseModel):
    version: int
    reviewer: str = Field(min_length=1)
    decision: Decision
    note: str = ''

class OrderWrite(BaseModel):
    version: int
    reviewer: str = Field(min_length=1)
    order: list[str]
