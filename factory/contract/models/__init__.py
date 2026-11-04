"""Models of the files every document folder contains (CONTRACT.md)."""

from .docir import Block, DocIR
from .document import BlockRef, DocumentManifest, PageEntry, PagePlan, Pagination
from .spec import BaseSpec, DocSpec
from .trace import Trace, TraceEvent
from .pipeline import (
    DesignCriterion,
    DesignLedgerEntry,
    DesignSpec,
    DocumentIndexEntry,
    DocumentRunRecord,
    ExtraStatements,
    LanguageStats,
    ProblemsRecord,
    RunRecord,
    SourceContent,
)

CONTRACT_VERSION = "0.2.0"
