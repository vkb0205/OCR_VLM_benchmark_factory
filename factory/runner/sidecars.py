"""Measure review sidecars without modifying any existing bundle file."""

import json
from pathlib import Path
import re

from factory.contract.extract import extract, parse_html
from factory.contract.lint import lint_document
from factory.contract.models import (
    BlockBox, Boxes, DocumentManifest, LintFinding, LintReport, PageBoxes,
)
from factory.runner.capture import measure_blocks


def bundles(path: Path) -> list[Path]:
    if (path / "document.json").is_file():
        return [path]
    return sorted(p.parent for p in path.glob("**/documents/*/*/document.json"))


def write_sidecar(folder: Path, name: str, model) -> None:
    extra = folder / "extra"
    extra.mkdir(exist_ok=True)
    temporary = extra / (name + ".tmp")
    temporary.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(extra / name)


async def write_boxes(folder: Path, browser, taxonomy) -> Boxes:
    manifest = DocumentManifest.model_validate_json((folder / "document.json").read_text(encoding="utf-8"))
    pages = []
    for entry in manifest.pages:
        path = folder / entry.file
        tree = parse_html(path.read_text(encoding="utf-8"))
        nodes = {n.attrs["data-gt-id"]: n for n in tree.walk() if "data-gt-id" in n.attrs}
        async with browser.page(path, device_scale_factor=manifest.image_dpi / 96) as (page, blocked, failed):
            if blocked or failed:
                raise ValueError(f"Failed resources: {blocked + failed}")
            measured = await measure_blocks(page, taxonomy.text, manifest.image_dpi)
            geometry = await page.evaluate("""(dpi) => {
                const b=document.body.getBoundingClientRect(), s=dpi/96;
                const poly=r=>[r.left-b.left,r.top-b.top,r.right-b.left,r.top-b.top,
                    r.right-b.left,r.bottom-b.top,r.left-b.left,r.bottom-b.top].map(v=>Math.round(v*s*100)/100);
                return {width:Math.round(b.width*s),height:Math.round(b.height*s),
                    ignored:[...document.querySelectorAll('[data-gt-ignore]')].map(e=>({poly:poly(e.getBoundingClientRect())}))};
            }""", manifest.image_dpi)
        blocks = []
        for box in measured:
            node = nodes[box["id"]]
            attrs = node.attrs
            blocks.append(BlockBox(
                id=box["id"], cat=box["category"], ro=box["order"], part=box.get("part"),
                poly=box["poly"], lang=attrs.get("data-gt-lang"), parent=attrs.get("data-gt-parent"),
                attrs={k.removeprefix("data-gt-attr-").replace("-", "_"): v
                       for k, v in attrs.items() if k.startswith("data-gt-attr-")},
                text=extract(node),
            ))
        pages.append(PageBoxes(index=entry.index, page_id=entry.page_id,
                               image_width=geometry["width"], image_height=geometry["height"],
                               blocks=blocks, ignored=geometry["ignored"]))
    result = Boxes(doc_id=manifest.doc_id, image_dpi=manifest.image_dpi, pages=pages)
    write_sidecar(folder, "boxes.json", result)
    return result


async def write_lint(folder: Path, browser, taxonomy):
    issues = await lint_document(folder, browser, taxonomy)
    content = json.loads((folder / "content.json").read_text(encoding="utf-8"))
    ids = {b["id"] for b in content["blocks"]}
    findings = []
    for issue in issues:
        # Existing rules include known IDs in their messages. Multiple IDs become
        # individual findings so each affected block can be selected in the UI.
        affected = [bid for bid in sorted(ids) if re.search(r"(?<![\w-])" + re.escape(bid) + r"(?![\w-])", issue.message)]
        for bid in affected or [None]:
            findings.append(LintFinding(rule_id=issue.rule_id, level=issue.level,
                                        page=issue.page, message=issue.message, block_id=bid))
    write_sidecar(folder, "lint.json", LintReport(doc_id=content["doc_id"], findings=findings))
    return issues
