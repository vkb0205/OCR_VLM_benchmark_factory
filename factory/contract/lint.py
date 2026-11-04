"""Static bundle checks and live-DOM offline/overflow checks."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re
from typing import NamedTuple
import unicodedata

from factory.contract.extract import Element, extract, extract_text, normalize, parse_html, table_html
from factory.contract.models import CONTRACT_VERSION, BaseSpec, DocIR, DocumentManifest, Pagination, Trace
from factory.contract.taxonomy import Taxonomy


class Violation(NamedTuple):
    rule_id: str
    level: str
    page: int | None
    message: str


def safe_path(root: Path, relative: str) -> Path:
    """Reject absolute paths and paths escaping the document bundle."""
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes bundle: {relative}")
    return path


def text_content(content) -> str:
    pieces = []
    for span in content.spans:
        pieces.append(f"${span.latex}$" if span.type == "equation_inline" else span.text)
    return normalize("".join(pieces))


def table_grid(node: Element) -> bool:
    """Check the expanded cell grid, rejecting overlaps and dangling row spans."""
    rows = [n for n in node.walk() if n.tag == "tr"]
    occupied, widths = set(), []
    try:
        for y, row in enumerate(rows):
            x = 0
            for cell in (c for c in row.children if isinstance(c, Element) and c.tag in {"th", "td"}):
                while (y, x) in occupied:
                    x += 1
                rs, cs = int(cell.attrs.get("rowspan", 1)), int(cell.attrs.get("colspan", 1))
                if rs < 1 or cs < 1 or y + rs > len(rows):
                    return False
                for yy in range(y, y + rs):
                    for xx in range(x, x + cs):
                        if (yy, xx) in occupied:
                            return False
                        occupied.add((yy, xx))
                x += cs
            width = max((xx + 1 for yy, xx in occupied if yy == y), default=0)
            if any((y, xx) not in occupied for xx in range(width)):
                return False
            widths.append(width)
    except ValueError:
        return False
    return bool(widths) and min(widths) > 0 and len(set(widths)) == 1


def lint_static(folder: Path, taxonomy: Taxonomy | None = None) -> list[Violation]:
    """Validate a document without launching a browser; errors are stable rule IDs."""
    folder, taxonomy = Path(folder), taxonomy or Taxonomy()
    issues = []

    def report(rule, message, page=None, level="E"):
        issues.append(Violation(rule, level, page, message))

    required = ["document.json", "content.json", "pagination.json", "spec.json", "trace.json", "style.css", "assets", "pages"]
    missing = [name for name in required if not (folder / name).exists()]
    if missing:
        report("C001", f"Missing required files: {', '.join(missing)}")
        return issues
    if any(not (folder / name).is_dir() for name in ("pages", "assets")):
        report("C001", "pages/ and assets/ must be directories")
        return issues
    try:
        manifest = DocumentManifest.model_validate_json((folder / "document.json").read_text())
        docir = DocIR.model_validate_json((folder / "content.json").read_text())
        pagination = Pagination.model_validate_json((folder / "pagination.json").read_text())
        spec = BaseSpec.model_validate_json((folder / "spec.json").read_text())
        trace = Trace.model_validate_json((folder / "trace.json").read_text())
        if any(obj.doc_id != manifest.doc_id for obj in (docir, pagination, spec, trace)):
            raise ValueError("Bundle document IDs disagree")
        if docir.doc_type != manifest.doc_type or spec.doc_type != manifest.doc_type:
            raise ValueError("Bundle document types disagree")
        if manifest.contract_version != CONTRACT_VERSION:
            raise ValueError("Unsupported contract version")
        if not re.fullmatch(re.escape(manifest.doc_type) + r"_\d{6}", manifest.doc_id):
            raise ValueError("Invalid document ID")
        if manifest.page_count != len(manifest.pages) or len(pagination.pages) != manifest.page_count:
            raise ValueError("Page counts disagree")
        if not spec.page_count[0] <= manifest.page_count <= spec.page_count[1]:
            raise ValueError("Page count outside spec range")
        if manifest.doc_type == 'academic_paper' and manifest.ro_level is not None:
            levels = {'L0', 'L1', 'L2', 'L3', 'L4'}
            if manifest.ro_level not in levels or spec.ro_level != manifest.ro_level:
                raise ValueError("Academic reading-order level is missing or disagrees")
            if spec.ro_cases != manifest.ro_cases:
                raise ValueError("Academic reading-order cases disagree")
            if any(page.ro_level not in levels or not page.ro_cases for page in manifest.pages):
                raise ValueError("Academic page reading-order metadata is missing")
    except (ValueError, OSError) as exc:
        report("C001", str(exc))
        return issues
    if manifest.taxonomy_version != taxonomy.version:
        report("C004", "Taxonomy version mismatch")
    for key, value in manifest.attributes.items():
        if not taxonomy.valid_attribute("page", key, value):
            report("C004", f"Invalid manifest attribute {key}={value}")
    blocks = {b.id: b for b in docir.blocks}
    if len(blocks) != len(docir.blocks):
        report("C005", "Duplicate block IDs in DocIR")
    seen = defaultdict(list)
    ordered = []
    for b in docir.blocks:
        if b.cat not in taxonomy.blocks:
            report("C004", f"Unknown DocIR category {b.cat}")
        for key, value in b.attrs.items():
            if not taxonomy.valid_attribute("block", key, value):
                report("C004", f"Invalid DocIR attribute {key}={value}")
        asset = getattr(b.content, "asset", None)
        if asset:
            try:
                if not safe_path(folder, asset).is_file():
                    report("C001", f"Missing asset {asset}")
            except ValueError as exc:
                report("C001", str(exc))
    for expected_index, entry in enumerate(manifest.pages, 1):
        index = entry.index
        if not taxonomy.valid_attribute("page", "page_kind", entry.kind):
            report("C004", f"Invalid page kind {entry.kind}", index)
        try:
            path = safe_path(folder, entry.file)
            html = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            report("C001", str(exc), index)
            continue
        if index != expected_index or entry.file != f"pages/page_{index:03}.html" or entry.page_id != f"{manifest.doc_id}_p{index:03}":
            report("C002", "Page naming/index does not match contract", index)
        size = re.search(r"@page\s*\{[^}]*size\s*:\s*([\d.]+)mm\s+([\d.]+)mm", html)
        if not size or (float(size[1]), float(size[2])) != (entry.width_mm, entry.height_mm):
            report("C002", "Missing/mismatched explicit @page size in mm", index)
        if html != unicodedata.normalize("NFC", html):
            report("C014", "HTML is not NFC", index)
        root = parse_html(html)
        if manifest.doc_type == 'academic_paper' and manifest.ro_level is not None:
            page_css = '\n'.join(''.join(n.children) for n in root.walk() if n.tag == 'style')
            if not re.search(r'hyphens\s*:\s*none\b', page_css, re.I):
                report("C013", "Academic page must disable CSS hyphenation", index)
        bodies = [n for n in root.walk() if n.tag == "body"]
        if len(bodies) != 1:
            report("C002", "Exactly one body required", index)
            continue
        body = bodies[0]
        expected = {"data-doc-id": manifest.doc_id, "data-page-id": entry.page_id, "data-page-index": str(index),
                    "data-page-role": entry.role, "data-page-kind": entry.kind, "data-page-doc-type": manifest.doc_type,
                    "data-page-lang": docir.lang}
        if any(body.attrs.get(k) != v for k, v in expected.items()) or "data-page-layout" not in body.attrs:
            report("C002", "Body attributes differ from manifest/DocIR", index)
        for key, value in body.attrs.items():
            if key.startswith("data-page-") and key not in {"data-page-id", "data-page-index", "data-page-role", "data-page-kind"}:
                if not taxonomy.valid_attribute("page", key.removeprefix("data-page-").replace("-", "_"), value):
                    report("C004", f"Invalid page attribute {key}={value}", index)
        page_nodes = []
        regions = [n for n in body.walk() if 'data-region' in n.attrs or 'data-chain' in n.attrs]
        if manifest.doc_type == 'academic_paper' and manifest.ro_level is not None and not regions:
            report("C013", "Academic page has no declared regions", index)
        chains = []
        for region in regions:
            try:
                if 'data-region' not in region.attrs:
                    raise ValueError()
                chain = int(region.attrs['data-chain'])
                if chain < 1:
                    raise ValueError()
                chains.append(chain)
            except (KeyError, ValueError):
                report("C013", "Region requires a positive integer data-chain", index)
        if len(chains) != len(set(chains)) or chains != sorted(chains):
            report("C013", "Region chain order is duplicated or out of order", index)
        for node in body.walk():
            cat = node.attrs.get("data-gt-cat")
            if cat is None:
                if "data-gt-id" in node.attrs or "data-gt-ro" in node.attrs:
                    report("C005", "Labeled node missing category", index)
                continue
            if cat not in taxonomy.blocks | taxonomy.spans:
                report("C004", f"Unknown category {cat}", index)
                continue
            ancestors, parent = [], node.parent
            while parent:
                ancestors.append(parent)
                parent = parent.parent
            if cat in taxonomy.spans:
                if not any(a.attrs.get("data-gt-cat") in taxonomy.text for a in ancestors):
                    report("C008", "Span outside text-bearing block", index)
                continue
            page_nodes.append(node)
            bid = node.attrs.get("data-gt-id")
            if not bid or bid not in blocks or "data-gt-ro" not in node.attrs:
                report("C005", f"Missing/unknown block ID or reading order: {bid}", index)
            if any(a.attrs.get("data-gt-cat") in taxonomy.blocks for a in ancestors):
                report("C008", f"Nested block {bid}", index)
            if cat in taxonomy.text and not taxonomy.valid_attribute("block", "lang", node.attrs.get("data-gt-lang", "")):
                report("C004", f"Missing/invalid language for {bid}", index)
            elif "data-gt-lang" in node.attrs and not taxonomy.valid_attribute("block", "lang", node.attrs["data-gt-lang"]):
                report("C004", f"Invalid block language for {bid}", index)
            for key, value in node.attrs.items():
                if key.startswith("data-gt-attr-") and not taxonomy.valid_attribute("block", key[13:].replace("-", "_"), value):
                    report("C004", f"Invalid block attribute {key}={value}", index)
            if cat == "table" and (node.tag != "table" or not table_grid(node)):
                report("C010", f"Invalid table structure {bid}", index)
            if bid in blocks:
                block = blocks[bid]
                if block.cat != cat or (block.lang and node.attrs.get("data-gt-lang") != block.lang):
                    report("C013", f"Category/language differs for {bid}", index)
                expected_attrs = {f'data-gt-attr-{k.replace("_", "-")}': v for k, v in block.attrs.items()}
                if any(node.attrs.get(k) != v for k, v in expected_attrs.items()) or node.attrs.get("data-gt-parent") != block.parent:
                    report("C013", f"Block attributes/parent differ for {bid}", index)
        try:
            ros = [int(n.attrs["data-gt-ro"]) for n in page_nodes]
            if sorted(ros) != list(range(1, len(ros) + 1)):
                raise ValueError()
        except (KeyError, ValueError):
            report("C006", "Reading order is not a permutation", index)
        page_nodes.sort(key=lambda n: int(n.attrs.get("data-gt-ro", "0")) if n.attrs.get("data-gt-ro", "0").isdigit() else 0)
        for node in page_nodes:
            bid = node.attrs.get("data-gt-id")
            if bid in blocks:
                seen[bid].append((index, node))
                if bid not in ordered:
                    ordered.append(bid)
        if expected_index <= len(pagination.pages):
            plan = pagination.pages[expected_index - 1]
            refs = plan.blocks
            if plan.index != index or plan.role != entry.role or [r.id for r in refs] != [n.attrs.get("data-gt-id") for n in page_nodes]:
                report("C012", "Pagination differs from rendered page block order", index)
            for ref, node in zip(refs, page_nodes):
                part = node.attrs.get("data-gt-part", "1/1")
                if part != f"{ref.part}/{ref.parts}":
                    report("C012", f"Pagination part mismatch: {ref.id}", index)
    for bid, block in blocks.items():
        occurrences = seen[bid]
        if not occurrences:
            report("C012", f"Unplaced DocIR block {bid}")
            continue
        pages = [i for i, n in occurrences]
        if len(occurrences) > 1 or "data-gt-part" in occurrences[0][1].attrs:
            parts = [n.attrs.get("data-gt-part") for _, n in occurrences]
            if parts != [f"{i}/{len(parts)}" for i in range(1, len(parts) + 1)]:
                report("C007", f"Incomplete/out-of-order pieces: {bid}")
                report("C012", f"Split coverage incomplete: {bid}")
        content = block.content
        if content.kind == "table":
            original = next((n for n in parse_html(content.html).walk() if n.tag == "table"), None)
            if original is None or not table_grid(original):
                report("C010", f"Invalid DocIR table: {bid}")
                continue
            original_rows = [n for n in original.walk() if n.tag == "tr"]
            headers, body_rows = original_rows[:content.header_rows], original_rows[content.header_rows:]
            actual_rows, ranges = [], []
            for page_index, node in occurrences:
                rows = [n for n in node.walk() if n.tag == "tr"]
                if [table_html(n) for n in rows[:content.header_rows]] != [table_html(n) for n in headers]:
                    report("C013", f"Repeated header changed: {bid}", page_index)
                actual_rows.extend(rows[content.header_rows:])
                refs = [r for p in pagination.pages if p.index == page_index for r in p.blocks if r.id == bid]
                if refs and refs[0].row_range is not None:
                    start, end = refs[0].row_range
                    ranges.append((start, end))
                    if [table_html(n) for n in rows[content.header_rows:]] != [table_html(n) for n in body_rows[start:end]]:
                        report("C012", f"Table row range differs from DOM: {bid}", page_index)
            if ranges and (ranges[0][0] != 0 or ranges[-1][1] != len(body_rows) or any(a[1] != b[0] for a, b in zip(ranges, ranges[1:]))):
                report("C012", f"Table row ranges have gaps/overlaps: {bid}")
            if [table_html(n) for n in actual_rows] != [table_html(n) for n in body_rows]:
                report("C013", f"Table cells differ from DocIR: {bid}")
        elif content.kind in {"text", "equation", "mark"}:
            expected_text = text_content(content) if content.kind == "text" else content.latex if content.kind == "equation" else content.value
            split = len(occurrences) > 1 or "data-gt-part" in occurrences[0][1].attrs
            actual = normalize(" ".join(extract(n) for _, n in occurrences) if split and content.kind == "text"
                               else "\n".join(extract(n) for _, n in occurrences))
            if actual != expected_text:
                report("C013", f"Extracted content differs from DocIR: {bid}")
    semantic_order = [b.id for b in docir.blocks if b.section != "page_furniture"]
    if manifest.doc_type != 'academic_paper' and [bid for bid in ordered if blocks[bid].section != "page_furniture"] != semantic_order:
        report("C013", "Document block reading order differs from DocIR")
    raw = json.dumps(docir.model_dump(mode="json"), ensure_ascii=False)
    if raw != unicodedata.normalize("NFC", raw):
        report("C014", "DocIR is not NFC")
    return issues


async def lint_document(folder: Path, browser, taxonomy: Taxonomy | None = None) -> list[Violation]:
    """Run static rules, then C003/C011/C015 in an offline browser."""
    folder = Path(folder)
    issues = lint_static(folder, taxonomy)
    if any(v.rule_id == "C001" for v in issues):
        return issues
    manifest = DocumentManifest.model_validate_json((folder / "document.json").read_text())
    for entry in manifest.pages:
        try:
            result = await browser.measure(safe_path(folder, entry.file))
            if result["blocked"] or result["failed"] or result.get("font_errors"):
                issues.append(Violation("C003", "E", entry.index, f"Resources blocked/failed: {result['blocked'] + result['failed'] + result.get('font_errors', [])}"))
            if result["uncovered"]:
                issues.append(Violation("C011", "E", entry.index, str(result["uncovered"])))
            if result["overflow"] or result["clipped"]:
                issues.append(Violation("C015", "W", entry.index,
                                        f"Overflow/clipped blocks: {result['clipped']}" if result["clipped"] else
                                        "the page content is larger than the sheet (a page box, main or a container "
                                        "is taller or wider than the page); no single block is clipped"))
            b = result["body"]
            if abs(b["width"] - entry.width_mm * 96 / 25.4) > 1 or abs(b["height"] - entry.height_mm * 96 / 25.4) > 1:
                issues.append(Violation("C002", "E", entry.index, "Body dimensions differ from manifest"))
        except Exception as exc:
            issues.append(Violation("C003", "E", entry.index, str(exc)))
    return issues
