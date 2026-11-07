"""Read and append compact, typed design-ledger entries."""

from __future__ import annotations

from pathlib import Path

from factory.contract.models import DesignLedgerEntry, DesignSpec
from factory.paths import OUT


def entries(doc_type: str, output: Path = OUT, limit: int | None = None) -> list[dict]:
    path = output / "index" / "designs.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = DesignLedgerEntry.model_validate_json(line)
        except ValueError:
            continue
        if row.doc_type == doc_type:
            rows.append({
                "doc_id": row.doc_id,
                "design_spec": row.design_spec.model_dump(mode="json"),
            })
    return rows if limit is None else rows[-limit:]


def _part(spec: dict, name: str) -> str:
    part = spec.get(name) or {}
    details = part.get("details") or {}
    if isinstance(details, dict):
        value = details.get("rule") or details.get("summary") or details.get("description")
    else:
        value = details
    value = value or part.get("chosen") or "-"
    return " ".join(str(value).split())[:90]


def summary(row: dict) -> str:
    spec = row.get("design_spec", row)
    style = spec.get("style") or {}
    palette = ",".join(style.get("palette", [])[:4])
    fonts = "/".join(style.get("fonts", [])[:2])
    if spec.get("mode") == "backbone":
        concept = (spec.get("brief") or row.get("brief") or {}).get("concept", "")
        plan = spec.get("layout_plan") or {}
        roles = plan.get("roles") or {}
        grid = ", ".join(f"{role}:{len(value.get('regions') or [])}r/{value.get('size', '?')}"
                          for role, value in roles.items())
        return (f"{row.get('doc_id', '?')}: {concept[:100]} / {grid} / {palette} / {fonts} / "
                f"table={spec.get('table_frame_type', '?')}")
    return (
        f"{row.get('doc_id', '?')}: {_part(spec, 'layout')} / {palette} / {fonts} / "
        f"{_part(spec, 'orientation')} / {_part(spec, 'reading_order')}"
    )


def recent(doc_type: str, output: Path = OUT, limit: int = 4) -> list[str]:
    return [summary(row) for row in entries(doc_type, output, limit)]


def append(doc_type: str, spec, output: Path = OUT, doc_id: str = "") -> None:
    path = output / "index" / "designs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump(mode="json") if isinstance(spec, DesignSpec) else spec
    model = DesignLedgerEntry(
        doc_id=doc_id,
        doc_type=doc_type,
        design_spec=DesignSpec.model_validate(data),
        content_id=data.get("content_id"),
        brief=data.get("brief") or {},
        fingerprint=data.get("fingerprint") or {},
        thumbnail_paths=data.get("thumbnail_paths") or [],
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(model.model_dump_json() + "\n")
