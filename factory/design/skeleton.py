"""Page structure for agent designs (option B).

Code owns the structure: pages, <main>, running header/footer, slot placement and the pagination
attributes come from the bundled default design. The design agent owns everything visual: CSS, sheet
size per page, and the order of the blocks inside each page's <main> (the reading order).
"""
from copy import deepcopy
from html import escape
import re

from factory.contract.extract import Element, parse_html
from factory.paths import ROOT
from factory.render.blocks import SIZES
from factory.render.fill import serialize

# Applied before the agent's CSS: the engine measures pages from these boxes.
BASE_CSS = ("*{box-sizing:border-box}html,body{margin:0;padding:0}"
            "section.page{position:relative;width:100%;height:100%;overflow:hidden}"
            # A chart or logo scales into its slot box instead of spilling over the caption.
            "section.page [data-slot]>svg,section.page [data-slot]>img,"
            "section.page [data-block]>svg,section.page [data-block]>img{display:block!important;"
            # max-height:inherit keeps an auto-height box's cap (figure{max-height:60mm}) on the drawing.
            "max-width:100%!important;width:100%!important;height:100%!important;max-height:inherit!important;"
            "object-fit:contain}"
            # Marks fill their slot's width, so a slot without a height would make them as tall as wide.
            # Cap logo, signature and seal slots; the drawing inherits the cap through max-height above.
            "section.page [data-slot$=logo]{max-height:45mm!important;max-width:90mm!important}"
            "section.page [data-slot^=signature_]:not([data-slot=signature_date]),section.page [data-slot$=_signature]"
            "{max-height:28mm!important;max-width:70mm!important}"
            "section.page [data-slot$=seal]{max-height:40mm!important;max-width:40mm!important}"
            # A seal is stamped over its signature inside .stamp, never over the signer's name below.
            "section.page .stamp{position:relative!important;min-height:26mm}"
            "section.page .stamp>[data-slot$=seal]{position:absolute!important;inset:auto!important;"
            "left:min(50%,35mm)!important;top:50%!important;transform:translate(-25%,-50%)!important;margin:0!important;"
            "width:24mm!important;height:24mm!important;max-width:24mm!important;max-height:24mm!important}"
            # Page frame, owned by code: header band at the top margin, footer and page number at the bottom
            # margin, <main> between them. The design styles these freely but cannot move them off the page.
            "section.page>header{position:absolute!important;top:var(--margin,15mm)!important;"
            "left:var(--margin,15mm)!important;right:var(--margin,15mm)!important;bottom:auto!important;"
            "height:auto!important;margin:0!important;transform:none!important}"
            "section.page>footer{position:absolute!important;bottom:var(--margin,15mm)!important;"
            "left:var(--margin,15mm)!important;right:calc(var(--margin,15mm) + 24mm)!important;top:auto!important;"
            "height:auto!important;margin:0!important;transform:none!important}"
            "section.page>.page-number{position:absolute!important;bottom:var(--margin,15mm)!important;"
            "right:var(--margin,15mm)!important;left:auto!important;top:auto!important;width:22mm!important;"
            "text-align:right!important;margin:0!important;transform:none!important}"
            "section.page>main{position:absolute!important;top:var(--margin,15mm)!important;"
            "bottom:var(--margin,15mm)!important;left:var(--margin,15mm)!important;right:var(--margin,15mm)!important;"
            "height:auto!important;max-height:none!important;margin:0!important;transform:none!important}"
            "section.page:has(>header)>main{top:calc(var(--margin,15mm) + 16mm)!important}"
            "section.page:has(>footer)>main,section.page:has(>.page-number)>main"
            "{bottom:calc(var(--margin,15mm) + 13mm)!important}"
            # Groups and signer boxes grow with their content; a fixed height there only overflows.
            "section.page .group,section.page .signer{height:auto!important;max-height:none!important}"
            "section.page td.num{white-space:nowrap}"
            # The engine paginates flowing content vertically; CSS multi-column would spill it sideways.
            "section.page main:has([data-split=auto]),section.page .group:has([data-split=auto]),"
            "section.page [data-split=auto]{column-count:auto!important;columns:auto!important}")


def _sections(doc_type: str) -> list[Element]:
    root = parse_html((ROOT / "designs" / doc_type / "default.html").read_text(encoding="utf-8"))
    return [node for node in root.walk()
            if node.tag == "section" and "page" in node.attrs.get("class", "").split()]


def _main(section: Element) -> Element | None:
    return next((node for node in section.walk() if node.tag == "main"), None)


def _key(node: Element, counts: dict[str, int]) -> str:
    """Stable name of a <main> child: its slot id, or label:<category>[#n]."""
    if node.attrs.get("data-slot"):
        return node.attrs["data-slot"]
    inner = next((n for n in node.walk() if n.attrs.get("data-slot")), None)
    if node.attrs.get("data-label"):
        base = "label:" + node.attrs["data-label"]
    elif inner is not None:
        base = "group:" + inner.attrs["data-slot"]
    else:
        base = "group"
    counts[base] = counts.get(base, 0) + 1
    return base if counts[base] == 1 else f"{base}#{counts[base]}"


def _children(main: Element) -> list[tuple[str, Element]]:
    counts: dict[str, int] = {}
    return [(_key(child, counts), child) for child in main.children if isinstance(child, Element)]


def _translate(section: Element, labels: list[str]) -> None:
    """Replace the fixed label texts in order (the default design is Vietnamese)."""
    nodes = [node for node in section.walk() if node.attrs.get("data-label")]
    if len(nodes) != len(labels):
        return
    for node, text in zip(nodes, labels):
        node.children = [str(text)]


def _clean(section: Element) -> None:
    for node in section.walk():
        node.attrs.pop("style", None)


def _unwrap_cover(section: Element) -> None:
    """The cover's wrapper divs are dissolved so each cover block can be placed on its own."""
    main = _main(section)
    if main is None:
        return
    def flat(node):
        out = []
        for child in node.children:
            if not isinstance(child, Element):
                continue
            if child.tag == "div" and not any(key.startswith("data-") for key in child.attrs):
                out.extend(flat(child))
            else:
                out.append(child)
        return out
    main.children = flat(main)
    for child in main.children:
        child.parent = main


def build_sections(doc_type: str, lang: str, fixed_labels: dict) -> list[Element]:
    sections = _sections(doc_type)
    for section in sections:
        _clean(section)
        if section.attrs.get("data-page-role") == "cover":
            _unwrap_cover(section)
        role = section.attrs.get("data-page-role", "")
        _translate(section, fixed_labels.get(lang, {}).get(role, []))
    return sections


def skeleton_prompt(doc_type: str, lang: str, fixed_labels: dict) -> str:
    """Compact structure shown to the agent; data-k names the <main> blocks it may reorder."""
    lines = []
    for section in build_sections(doc_type, lang, fixed_labels):
        main = _main(section)
        if main is not None:
            for key, child in _children(main):
                child.attrs["data-k"] = key
        html = re.sub(r"\s+", " ", serialize(section))
        lines.append(re.sub(r">[^<]{40,}<", ">…<", html))
    return "\n".join(lines)


def _class_names(value, limit: int = 6) -> str:
    return " ".join(re.findall(r"[A-Za-z][\w-]*", str(value or ""))[:limit])


def _group(main: Element, groups) -> None:
    """Wrap listed <main> blocks in <div class=...> containers, placed where their first block was."""
    if not isinstance(groups, list):
        return
    children = _children(main)
    by_key = dict(children)
    owner, wrappers = {}, []
    for index, group in enumerate(groups[:8]):
        if not isinstance(group, dict):
            continue
        items = [key for key in dict.fromkeys(map(str, group.get("items") or [])) if key in by_key and key not in owner]
        if not items:
            continue
        wrapper = Element("div", {"class": "group " + (_class_names(group.get("class")) or f"group-{index + 1}")},
                          parent=main)
        wrapper.children = [by_key[key] for key in items]
        for key in items:
            owner[key] = wrapper
            by_key[key].parent = wrapper
        wrappers.append(wrapper)
    out, placed = [], set()
    for key, child in children:
        wrapper = owner.get(key)
        if wrapper is None:
            out.append(child)
        elif id(wrapper) not in placed:
            placed.add(id(wrapper))
            out.append(wrapper)
    main.children = out


def _decorate(section: Element, names) -> None:
    """Empty, text-free decoration elements; the engine labels them as ignored."""
    for name in (names if isinstance(names, list) else [])[:4]:
        cls = _class_names(name, 3)
        if cls:
            node = Element("div", {"class": "decor " + cls, "data-gt-ignore": "", "aria-hidden": "true"},
                           parent=section)
            section.children.insert(0, node)


def build_design(doc_type: str, lang: str, fixed_labels: dict, css: str, pages: dict,
                 params: dict | None = None) -> str:
    """Full design HTML from the fixed structure plus the agent's CSS and per-page choices.

    pages: {role|"all": {"order": [data-k], "groups": [{"class", "items": [data-k]}],
                          "decor": [class names], "class": "extra classes", "size", "frame"}}
    With params (design/params.py) code sets sheet sizes, table frames and chart style itself.
    Unknown keys are ignored; children not listed keep their default order after the listed ones.
    """
    from factory.design.params import css_variables, frame_css, page_size

    built = []
    every = pages.get("all") if isinstance(pages.get("all"), dict) else {}
    for section in build_sections(doc_type, lang, fixed_labels):
        role = section.attrs.get("data-page-role", "")
        choice = pages.get(role) or {}
        size = page_size(params, role) if params else str(choice.get("size") or section.attrs.get("data-size", "a4"))
        section.attrs["data-size"] = size if size in SIZES else "a4"
        if params:
            for table in (node for node in section.walk() if node.tag == "table" or node.attrs.get("data-frame")):
                table.attrs["data-frame"] = params["frame"]
        extra = _class_names(choice.get("class"))
        section.attrs["class"] = f"page role-{role}" + (f" {extra}" if extra else "")
        main = _main(section)
        order = choice.get("order")
        if main is not None and isinstance(order, list):
            children = _children(main)
            by_key = dict(children)
            listed = [by_key[key] for key in dict.fromkeys(map(str, order)) if key in by_key]
            rest = [child for _, child in children if child not in listed]
            main.children = listed + rest
        if main is not None:
            _group(main, choice.get("groups"))
        _decorate(section, list(every.get("decor") or []) + list(choice.get("decor") or []))
        built.append(serialize(deepcopy(section)))
    css = re.sub(r"</style", "<\\/style", str(css), flags=re.I)
    chart = ""
    head_css = BASE_CSS
    if params:
        forms = ",".join(f"{kind}:{form}" for kind, form in params["chart_forms"].items())
        chart = (f' data-chart-colors="{escape(",".join(params["chart_colors"]))}"'
                 f' data-chart-forms="{escape(forms)}"')
        head_css = css_variables(params) + BASE_CSS + frame_css(params)
    return (f'<!doctype html><html lang="{escape(lang)}"{chart}><head><meta charset="utf-8">'
            f"<style>{head_css}\n{css}</style></head><body>\n" + "\n".join(built) + "\n</body></html>")
