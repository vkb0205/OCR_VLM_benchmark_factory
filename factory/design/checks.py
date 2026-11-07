"""Static and browser checks for generated document designs."""

from __future__ import annotations

import colorsys
import json
import math
from pathlib import Path

from factory.contract.extract import parse_html
from factory.render.blocks import SIZES


CRITERIA = ("layout", "style", "reading_order", "orientation")


def rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError("expected #RRGGBB")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def hue(value: str) -> float:
    return colorsys.rgb_to_hsv(*rgb(value))[0] * 360


def hue_gap(left: float, right: float) -> float:
    delta = abs(left - right) % 360
    return min(delta, 360 - delta)


def luminance(value: str) -> float:
    channels = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
                for channel in rgb(value)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(left: str, right: str) -> float:
    high, low = sorted((luminance(left), luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _spec_from_ledger(entry) -> dict:
    if not isinstance(entry, dict):
        return {}
    return entry.get("design_spec", entry)


def _page_sizes(html: str) -> dict[str, str]:
    root = parse_html(html)
    sections = [node for node in root.walk()
                if node.tag == "section" and "page" in node.attrs.get("class", "").split()]
    return {f"page_{index:03}": node.attrs.get("data-size", "")
            for index, node in enumerate(sections, 1)}


def _check_backbone(folder: Path, spec: dict) -> list[str]:
    from factory.design.backbone import BackboneError, validate_plan
    from factory.design.fonts import get_font

    problems = []
    if not spec.get("content_id"):
        problems.append("content_id missing from backbone design")
    if spec.get("params"):
        problems.append("backbone design must not contain code-drawn params")
    if spec.get("draws"):
        problems.append("backbone design must not contain code-drawn option draws")
    style = spec.get("style") or {}
    palette = style.get("palette") or []
    if len(palette) < 3:
        problems.append("style: background, ink, and accent colors are required")
    for index, color in enumerate(palette, 1):
        try:
            rgb(color)
        except (ValueError, AttributeError):
            problems.append(f"style: palette color {index} must be #RRGGBB")
    if len(palette) >= 2:
        try:
            ratio = contrast(palette[0], palette[1])
            if ratio < 4.5:
                problems.append(f"style: declared paper/ink contrast is {ratio:.2f}:1, below 4.5:1")
        except (ValueError, IndexError):
            problems.append("style: palette entries must be #RRGGBB colors")
    families = style.get("fonts") or []
    if len(families) != 2 or str(families[0]).casefold() == str(families[1]).casefold():
        problems.append("style: distinct heading/body registry families are required")
    else:
        for family in families:
            try:
                get_font(str(family))
            except KeyError:
                problems.append(f"style: font family {family!r} is absent from the Vietnamese registry")
    if spec.get("table_frame_type") not in {"full_line", "less_line", "fewer_line", "wireless_line"}:
        problems.append("table_frame_type is not a supported frame type")
    plan = spec.get("layout_plan") or {}
    try:
        validate_plan(plan, _academic_config())
    except (BackboneError, ValueError, TypeError, KeyError) as exc:
        problems.append(f"layout_plan: {exc}")
    source_html = folder / "design" / "design.html"
    if source_html.is_file():
        actual = _page_sizes(source_html.read_text(encoding="utf-8"))
        declared = (spec.get("orientation") or {}).get("pages") or {}
        if declared != actual:
            problems.append("orientation.pages does not match rendered design page sizes")
    return problems


def _academic_config():
    from factory.content.config import load_config
    return load_config().documents["academic_paper"].for_lang("vi")


def check(folder, ledger=(), warnings: list | None = None):
    """Validate design choices and compare only with the four newest ledger entries.

    Returns blocking problems. Bookkeeping slips (draw/index/declared palette) go to `warnings`:
    they describe the spec, not the rendered page, which the browser checks measure directly.
    """
    folder = Path(folder)
    problems = []
    warnings = [] if warnings is None else warnings
    spec_path = next(iter(sorted(folder.glob("**/design_spec.json"))), None)
    if spec_path is None:
        return ["design_spec.json missing"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("mode") == "backbone":
        return _check_backbone(folder, spec)
    if "seed" not in spec:
        problems.append("seed missing")

    skipped = {row.get("criterion"): row for row in spec.get("skipped", [])
               if isinstance(row, dict)}
    for name, row in skipped.items():
        if not row.get("reason"):
            problems.append(f"{name}: skipped option needs a reason")
        if name not in CRITERIA or row.get("index") != (spec.get(name) or {}).get("index"):
            problems.append(f"{name}: skipped index does not match the chosen criterion index")
    all_draws = spec.get("draws") or {}
    for name in CRITERIA:
        part = spec.get(name) or {}
        if "details" not in part:
            problems.append(f"{name}: details missing")
        options = part.get("options") or []
        draw_values = all_draws.get(name) or []
        valid_draws = len(draw_values) == 6 and all(
            isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value < 1
            for value in draw_values
        )
        if not valid_draws:
            problems.append(f"{name}: needs six draws in [0,1)")
        if (part.get("details") or {}).get("source") == "code":
            continue  # chosen by code from the seed (orientation size plan)
        if len(options) < 10 or len(set(map(str, options))) != len(options):
            problems.append(f"{name}: needs at least 10 distinct options")
            continue
        index = part.get("index")
        selected = options[index] if type(index) is int and 0 <= index < len(options) else None
        if part.get("chosen") != selected:
            warnings.append(f"{name}: chosen is not options[index]")
        if valid_draws:
            expected = math.floor(round(draw_values[0], 4) * len(options))
            if index != expected and name not in skipped:
                warnings.append(f"{name}: index {index} does not follow rounded draw (expected {expected})")

    style = spec.get("style") or {}
    palette = style.get("palette") or []
    if len(palette) < 3:
        problems.append("style: background, ink, and accent colors are required")
    for index, color in enumerate(palette, 1):
        try:
            rgb(color)
        except (ValueError, AttributeError):
            problems.append(f"style: palette color {index} must be #RRGGBB")
    fonts = style.get("fonts") or []
    if (len(fonts) != 2 or any(not str(font).strip() for font in fonts)
            or (len(fonts) == 2 and str(fonts[0]).strip().casefold() == str(fonts[1]).strip().casefold())):
        problems.append("style: heading/body font pairing is required")
    if len(palette) >= 2:
        try:
            ratio = contrast(palette[0], palette[1])
            if ratio < 4.5:
                warnings.append(f"style: declared background/ink contrast {ratio:.1f} is below 4.5")
        except (ValueError, IndexError):
            problems.append("style: palette entries must be #RRGGBB colors")
    if len(palette) >= 3:
        try:
            saturation = colorsys.rgb_to_hsv(*rgb(palette[2]))[1]
            if saturation < 0.12:
                warnings.append("style: accent color needs a distinct hue")
        except (ValueError, IndexError, AttributeError):
            pass

    # Distinct means not a near-copy: one shared trait with a recent design is fine, two or more are not.
    for row in list(ledger)[-4:]:
        previous = _spec_from_ledger(row)
        doc_id = row.get("doc_id", "recent design") if isinstance(row, dict) else "recent design"
        mine, theirs = spec.get("params") or {}, previous.get("params") or {}
        if mine and theirs:
            # Code drew orientation, fonts and accent: compare the draws, plus the agent's own criteria.
            from factory.design.params import shared_traits
            shared = shared_traits(mine, theirs) + [
                f"same {name} option" for name in CRITERIA if name != "orientation"
                and str((spec.get(name) or {}).get("chosen", "")).strip().casefold()
                == str((previous.get(name) or {}).get("chosen", "")).strip().casefold()]
            if len(shared) >= 2:
                problems.append(f"{doc_id}: too similar to a recent design ({', '.join(shared)})")
            elif shared:
                warnings.append(f"{doc_id}: {shared[0]}")
            continue
        shared = [f"same {name} option" for name in CRITERIA
                  if str((spec.get(name) or {}).get("chosen", "")).strip().casefold()
                  == str((previous.get(name) or {}).get("chosen", "")).strip().casefold()]
        other_fonts = (previous.get("style") or {}).get("fonts") or []
        if len(fonts) == 2 and len(other_fonts) == 2:
            pair = tuple(str(font).strip().casefold() for font in fonts)
            other_pair = tuple(str(font).strip().casefold() for font in other_fonts)
            if pair == other_pair:
                shared.append("same heading/body font pairing")
        other_palette = (previous.get("style") or {}).get("palette") or []
        if len(palette) > 2 and len(other_palette) > 2:
            try:
                if hue_gap(hue(palette[2]), hue(other_palette[2])) < 25:
                    shared.append("accent hue within 25 degrees")
            except (ValueError, IndexError):
                pass
        if len(shared) >= 2:
            problems.append(f"{doc_id}: too similar to a recent design ({', '.join(shared)})")
        elif shared:
            warnings.append(f"{doc_id}: {shared[0]}")

    source_html = folder / "design" / "design.html"
    if source_html.is_file():
        source = source_html.read_text(encoding="utf-8")
        actual = _page_sizes(source)
        declared = (spec.get("orientation") or {}).get("pages") or {}
        if declared != actual:
            for name in sorted(set(declared) | set(actual)):
                if declared.get(name) != actual.get(name):
                    problems.append(
                        f"orientation.pages[{name}] is {declared.get(name)!r}; "
                        f"HTML data-size is {actual.get(name)!r}"
                    )
        root = parse_html(source)
        if any(any(attribute.startswith("data-gt-") and attribute != "data-gt-ignore" for attribute in node.attrs)
               for node in root.walk()):
            problems.append("design HTML: data-gt-* attributes are generated by code and are not allowed")
    else:
        problems.append("design/design.html missing for orientation check")
    return problems


async def browser_checks(folder, browser, min_font_px: float = 9):
    problems = []
    for path in sorted((Path(folder) / "pages").glob("*.html")):
        async with browser.page(path) as (page, blocked, failed):
            if blocked or failed:
                problems.append(f"{path.name}: blocked assets {blocked + failed}")
                continue
            found = await page.evaluate("""(minFontPx) => {
              const out=[], els=[...document.querySelectorAll('[data-gt-id]')];
              const rgb=s=>(s.match(/[\\d.]+/g)||[]).slice(0,3).map(Number);
              const lum=c=>c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4})
                .reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
              for(const e of els){
                const s=getComputedStyle(e);
                for(const child of e.querySelectorAll('*')){
                  if(child.textContent.trim()&&parseFloat(getComputedStyle(child).fontSize)<minFontPx)
                    out.push('font below '+minFontPx+'px inside: '+e.dataset.gtId);
                }
                if(parseFloat(s.fontSize)<minFontPx)out.push('font below '+minFontPx+'px: '+e.dataset.gtId);
                let bg=e;while(bg.parentElement && getComputedStyle(bg).backgroundColor==='rgba(0, 0, 0, 0)')bg=bg.parentElement;
                const a=lum(rgb(s.color)),b=lum(rgb(getComputedStyle(bg).backgroundColor));
                if(e.textContent.trim()&&(Math.max(a,b)+.05)/(Math.min(a,b)+.05)<4.5)out.push('text contrast: '+e.dataset.gtId);
              }
              for(const e of els){
                if(!e.textContent.trim())continue;
                const r=e.getBoundingClientRect();
                for(const d of document.querySelectorAll('svg,[data-gt-ignore]')){
                  if(d.contains(e)||e.contains(d)||d.closest('[data-gt-id]'))continue;
                  const q=d.getBoundingClientRect();
                  if(Math.min(r.right,q.right)-Math.max(r.left,q.left)>2&&Math.min(r.bottom,q.bottom)-Math.max(r.top,q.top)>2)
                    out.push('decoration overlaps text: '+e.dataset.gtId);
                }
              }
              for(let i=0;i<els.length;i++)for(let j=i+1;j<els.length;j++){
                const a=els[i],b=els[j];if(a.contains(b)||b.contains(a))continue;
                const cats=[a.dataset.gtCat,b.dataset.gtCat];if(cats.includes('seal')&&cats.includes('signature'))continue;
                const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();
                if(Math.min(x.right,y.right)-Math.max(x.left,y.left)>2&&Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)>2)
                  out.push('overlap: '+a.dataset.gtId+' / '+b.dataset.gtId);
              }
              return out;
            }""", min_font_px)
        problems.extend(f"{path.name}: {problem}" for problem in found)
    return problems


async def check_backbone_geometry(folder, layout_plan, content_config, browser):
    """Check rendered sheet sizes and measured region boxes against a backbone plan."""
    from factory.design.backbone import validate_plan
    from factory.contract.models import DocumentManifest

    folder = Path(folder)
    manifest = DocumentManifest.model_validate_json((folder / "document.json").read_text(encoding="utf-8"))
    plan = validate_plan(layout_plan, content_config)
    problems = []
    for entry in manifest.pages:
        path = folder / entry.file
        source = path.read_text(encoding="utf-8")
        root = parse_html(source)
        section = next((node for node in root.walk() if node.tag == "section" and "page" in node.attrs.get("class", "").split()), None)
        if section is None:
            problems.append(f"page {entry.index}: section.page is missing")
            continue
        is_wide = "data-wide-table-active" in section.attrs
        role = entry.role
        expected_size = plan["wide_table_page"]["size"] if is_wide and plan.get("wide_table_page") else plan["roles"][role]["size"]
        expected_dims = SIZES[expected_size]
        if abs(entry.width_mm - expected_dims[0]) > 0.01 or abs(entry.height_mm - expected_dims[1]) > 0.01:
            problems.append(f"page {entry.index}: rendered size {(entry.width_mm, entry.height_mm)} != {expected_size} {expected_dims}")
        expected_geometry = (plan["wide_table_page"]["_geometry"] if is_wide and plan.get("wide_table_page")
                             else plan["_geometry"][role])
        async with browser.page(path) as (page, blocked, failed):
            if blocked or failed:
                problems.append(f"page {entry.index}: blocked resources while measuring regions: {blocked + failed}")
                continue
            measured = await page.evaluate("""() => {
              const main=document.querySelector('section.page>main');
              if(!main) return null;
              const m=main.getBoundingClientRect();
              return [...main.querySelectorAll('[data-region]')].map(n=>{
                const r=n.getBoundingClientRect();
                return {chain:parseInt(n.dataset.chain||'0',10),box:[
                  (r.left-m.left)*25.4/96,(r.top-m.top)*25.4/96,
                  r.width*25.4/96,r.height*25.4/96
                ]};
              }).sort((a,b)=>a.chain-b.chain);
            }""")
        if measured is None or len(measured) != len(expected_geometry):
            problems.append(f"page {entry.index}: rendered region count differs from the plan")
            continue
        for actual, (chain, name, expected_box) in zip(measured, expected_geometry):
            if actual["chain"] != chain:
                problems.append(f"page {entry.index}: region {name} chain {actual['chain']} != {chain}")
                continue
            differences = [abs(got - want) for got, want in zip(actual["box"], expected_box)]
            if any(value > 1.0 for value in differences):
                problems.append(f"page {entry.index}: region {name} differs from plan by {differences} mm")
    return problems


def summarize_problems(problems, limit: int = 20) -> str:
    """Dedupe and group check problems so repair prompts stay small.

    Lines look like "page_003.html: overlap: a / b"; they are grouped by their kind
    ("overlap", "font below 9px", ...) with a count and a few examples each.
    """
    lines = []
    for problem in problems:
        lines.extend(line.strip() for line in str(problem).splitlines() if line.strip())
    groups: dict[str, list[str]] = {}
    for line in dict.fromkeys(lines):
        page, separator, rest = line.partition(".html: ")
        body = rest if separator else line
        kind = body.split(":", 1)[0].strip()[:60]
        groups.setdefault(kind, []).append(line)
    output = []
    for kind, rows in sorted(groups.items(), key=lambda item: -len(item[1])):
        if len(output) >= limit:
            output.append(f"... {len(groups) - len(output)} more problem kinds omitted")
            break
        if len(rows) == 1:
            output.append(rows[0][:300])
        else:
            examples = "; ".join(row[:160] for row in rows[:3])
            output.append(f"{kind}: {len(rows)} cases, e.g. {examples}")
    return "\n".join(output)

