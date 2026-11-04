"""In-memory document bundles shared by renderer and writer."""

from dataclasses import dataclass, field

from factory.contract.models import BaseSpec, DocIR, DocumentManifest, Pagination, Trace


@dataclass
class DocumentResult:
    """Contract files plus optional assets and renderer-owned sidecars."""

    content: DocIR
    pagination: Pagination
    pages: dict[str, str]
    manifest: DocumentManifest
    spec: BaseSpec
    trace: Trace
    style: str
    assets: dict[str, bytes] = field(default_factory=dict)
    extra: dict[str, bytes] = field(default_factory=dict)


