"""Fix the spelling of a model-written design before it is validated.

Only form is changed here: label category names, table frame attributes, empty table slots written
as <div>, stray data-gt-* attributes and event handlers. Layout, text and slot placement are left
for the checks.
"""
import random
import re

from factory.paths import ROOT

FONT_DIR = ROOT / "designs/_fonts"
FRAMES = ["full_line", "less_line", "fewer_line", "wireless_line"]

# Words in an invented label name -> taxonomy text category; first match wins.
LABEL_HINTS = [
    (("page_number", "pagenumber", "page_no", "folio", "pagination", "page"), "page_number"),
    (("footnote", "note_mark"), "footnote"),
    (("footer", "running_footer"), "footer"),
    (("header", "running_header", "masthead"), "header"),
    (("caption_table", "table_caption", "table_title"), "caption_table"),
    (("caption_chart", "chart_caption", "chart_title"), "caption_chart"),
    (("caption_figure", "figure_caption"), "caption_figure"),
    (("caption",), "caption_table"),
    (("document_title", "report_title", "cover_title", "title"), "title"),
    (("heading", "section", "subtitle", "statement_title", "kicker"), "section_header"),
    (("list", "bullet", "item"), "list_item"),
    (("reference", "citation"), "reference"),
]

OPEN_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*?)?(/?)>")
ATTR = re.compile(r'\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s"\'=<>`]+))?')


def label_category(name: str, known: set[str]) -> str:
    """Map an invented label name to a taxonomy text category (text_block when nothing matches)."""
    if name in known:
        return name
    lowered = name.casefold()
    for words, category in LABEL_HINTS:
        if category in known and any(word in lowered for word in words):
            return category
    return "text_block"


def _attrs(source: str) -> list[tuple[str, str | None]]:
    return [(match.group(1), match.group(2)) for match in ATTR.finditer(source or "")]


def _value(raw: str | None) -> str:
    if raw is None:
        return ""
    return raw[1:-1] if raw[:1] in "\"'" else raw


def _render(tag: str, attrs: list[tuple[str, str | None]], closing: str) -> str:
    parts = [tag] + [name if raw is None else f"{name}={raw}" for name, raw in attrs]
    return "<" + " ".join(parts) + closing + ">"


def _document(html: str, notes: list[str]) -> str:
    """Put every <style> into <head>: the fill engine copies page CSS from <head> only."""
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", html, flags=re.S | re.I)
    head = re.search(r"<head\b[^>]*>(.*?)</head>", html, flags=re.S | re.I)
    loose = re.sub(r"<head\b[^>]*>.*?</head>", "", html, flags=re.S | re.I)
    if head and not re.search(r"<style\b", loose, flags=re.I):
        return html
    body = re.sub(r"<style\b[^>]*>.*?</style>", "", loose, flags=re.S | re.I)
    body = re.sub(r"</?(?:!doctype|html|body)\b[^>]*>", "", body, flags=re.I)
    notes.append(f"moved {len(styles)} <style> element(s) into <head>")
    css = "\n".join(styles)
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            f"<body>{body.strip()}</body></html>")


def tidy_design(html: str, config, taxonomy, seed: int = 0) -> tuple[str, list[str]]:
    """Return the corrected HTML and a list of the corrections made (for the trace)."""
    known = set(taxonomy.text)
    tables = {field.id for field in config.fields if field.kind in {"table", "statement"}}
    # Slots that may continue on a new page, and elements repeated on continuation pages.
    flowing = tables | {field.id for field in config.fields if field.kind in {"notes", "kpis"}}
    repeated_slots = {"running_header", "running_footer"}
    repeated_labels = {"header", "footer", "page_number"}
    frame = random.Random(seed).choice(FRAMES)
    notes: list[str] = []

    def fix(match: re.Match) -> str:
        tag, source, closing = match.group(1), match.group(2) or "", match.group(3)
        attrs = _attrs(source)
        kept = []
        for name, raw in attrs:
            lowered = name.lower()
            if lowered.startswith("on") or (lowered.startswith("data-gt-") and lowered != "data-gt-ignore"):
                notes.append(f"removed {name} on <{tag}>")
                continue
            if lowered == "data-label":
                label = _value(raw)
                category = label_category(label, known)
                if category != label:
                    notes.append(f"label {label} -> {category}")
                    raw = f'"{category}"'
            kept.append((name, raw))
        slot = next((_value(raw) for name, raw in kept if name == "data-slot"), None)
        label = next((_value(raw) for name, raw in kept if name == "data-label"), None)
        present = {name for name, _ in kept}
        if slot in flowing and "data-split" not in present:
            kept.append(("data-split", '"auto"'))
            notes.append(f"{slot}: added data-split=auto")
        if (slot in repeated_slots or label in repeated_labels) and "data-continued" not in present:
            kept.append(("data-continued", None))
            notes.append(f"{slot or label}: added data-continued")
        if slot in tables:
            current = next((_value(raw) for name, raw in kept if name == "data-frame"), None)
            if current not in FRAMES:
                kept = [(name, raw) for name, raw in kept if name != "data-frame"] + [("data-frame", f'"{frame}"')]
                notes.append(f"{slot}: data-frame {current or 'missing'} -> {frame}")
        return _render(tag, kept, closing)

    html = OPEN_TAG.sub(fix, html)
    html = _document(html, notes)

    # A slot placed twice: keep the first, drop later empty copies.
    seen: set[str] = set()

    def first_only(match: re.Match) -> str:
        slot = match.group(3)
        if slot in seen:
            notes.append(f"{slot}: removed duplicate placement")
            return ""
        seen.add(slot)
        return match.group(0)

    html = re.sub(r'<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*?\bdata-slot\s*=\s*["\']([^"\']+)["\'][^<>]*)>\s*</\1>',
                  first_only, html)

    # All CSS must be inline: stylesheet links and @import point at files the model never supplies.
    def drop(match: re.Match) -> str:
        notes.append(f"removed {match.group(0)[:80]}")
        return ""

    html = re.sub(r'<link\b[^<>]*\brel\s*=\s*["\']?stylesheet["\']?[^<>]*>', drop, html, flags=re.I)
    html = re.sub(r'@import\b[^;]*;', drop, html, flags=re.I)

    # Font URLs point at the bundled files under assets/fonts/.
    fonts = {path.name for path in FONT_DIR.iterdir() if path.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}}

    def font_url(match: re.Match) -> str:
        quote, url = match.group(1), match.group(2)
        name = url.rsplit("/", 1)[-1]
        if name in fonts and url != f"assets/fonts/{name}":
            notes.append(f"font url {url} -> assets/fonts/{name}")
            url = f"assets/fonts/{name}"
        return f"url({quote}{url}{quote})"

    html = re.sub(r'url\(\s*(["\']?)([^"\')]+)\1\s*\)', font_url, html)

    # An empty table slot written as another element becomes a <table>.
    def to_table(match: re.Match) -> str:
        notes.append(f"{match.group(3)}: <{match.group(1)}> slot -> <table>")
        return f"<table{match.group(2)}></table>"

    for slot in tables:
        pattern = re.compile(
            r'<(div|section|figure|span|p)(\s[^<>]*\bdata-slot\s*=\s*["\'](' + re.escape(slot) + r')["\'][^<>]*)>\s*</\1>'
        )
        html = pattern.sub(to_table, html)
    return html, notes
