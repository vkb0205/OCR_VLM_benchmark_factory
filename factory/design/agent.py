"""Render and check a design reply without owning an LLM conversation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from factory.contract.extract import extract_text, parse_html
from factory.contract.lint import lint_document
from factory.contract.models import DesignSpec, TraceEvent
from factory.design.checks import browser_checks, check
from factory.design.draws import draws
from factory.render.blocks import SIZES
from factory.render.fill import fill, validate_template
from factory.render.metrics import page_fill
from factory.runner.writer import write_bundle
from factory.log import log
from factory.paths import ROOT
from factory.design.tidy import tidy_design
from factory.design.skeleton import build_design
from factory.design.params import SIZE_PLANS, draw_params


def page_sizes(html: str) -> dict[str, str]:
    """data-size of every page section, in DOM order: {"page_001": "a4", ...}."""
    root = parse_html(html)
    sections = [node for node in root.walk()
                if node.tag == "section" and "page" in node.attrs.get("class", "").split()]
    return {f"page_{index:03}": node.attrs.get("data-size", "") for index, node in enumerate(sections, 1)}


def orientation_problems(html: str, design_spec: DesignSpec) -> list[str]:
    """The HTML is the source of truth for sizes; design_spec.orientation.pages is copied from it."""
    actual = page_sizes(html)
    if not actual:
        return ["design has no <section class=\"page\"> pages"]
    return [f"{name}: data-size {size!r} is not one of {', '.join(SIZES)}"
            for name, size in actual.items() if size not in SIZES]


async def render_design(agent, content, spec, target: Path, reply):
    """Validate a blank design, fill it, and save the intermediate bundle."""
    raw_spec = dict(reply.design_spec)
    lang = content.lang or spec.lang
    backbone_mode = content.config.design.get("mode") == "backbone"
    table_frame = None
    layout_plan = None
    if backbone_mode:
        direction = getattr(agent, 'current_direction', None)
        if direction:
            from factory.design.direction import build as build_direction
            expected_plan, base_css = build_direction(direction, content.config)
            if reply.layout_plan != expected_plan:
                raise ValueError('direction: layout_plan must preserve the code-drawn geometry and size')
            if list((raw_spec.get('style') or {}).get('fonts', [])) != direction['fonts']:
                raise ValueError('direction: preserve drawn font pairing')
            raw_spec['direction'] = direction
        from factory.design.backbone import load_backbone
        from factory.design.fonts import font_face_css, get_font

        layout_plan = reply.layout_plan
        if not isinstance(layout_plan, dict) or not layout_plan:
            raise ValueError("apply_design must provide a complete layout_plan")
        style = dict(raw_spec.get("style") or {})
        palette = style.get("palette") or []
        if len(palette) < 3 or any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
                                   for color in palette):
            raise ValueError("design_spec.style.palette needs at least three #RRGGBB colors")
        fonts = style.get("fonts") or []
        if len(fonts) != 2:
            raise ValueError("design_spec.style.fonts must name heading and body families")
        chosen_fonts = [get_font(str(name)).name for name in fonts]
        style["fonts"] = chosen_fonts
        raw_spec["style"] = style
        frame_table_type = raw_spec.get("table_frame_type") or style.get("table_frame_type")
        if frame_table_type not in {"full_line", "less_line", "fewer_line", "wireless_line"}:
            raise ValueError("design_spec.table_frame_type must be full_line, less_line, fewer_line, or wireless_line")
        table_frame = frame_table_type
        body_size = float((layout_plan.get("roles") or {}).get("body", {}).get("body_font_size_pt", 10))
        details = style.get("details") if isinstance(style.get("details"), dict) else {}
        leading = float(details.get("leading", 1.35))
        frame_margin = load_backbone()["frame"]["margin_mm"]
        theme = (
            f':root{{--font-head:"{chosen_fonts[0]}",serif;--font-body:"{chosen_fonts[1]}",serif;'
            f'--paper:{palette[0]};--ink:{palette[1]};--accent:{palette[2]};'
            f'--base-size:{body_size:g}pt;--leading:{leading:g};--margin:{frame_margin:g}mm}}'
            f'body{{font-family:var(--font-body);font-size:var(--base-size);line-height:var(--leading);'
            f'color:var(--ink);background:var(--paper)}}section.page{{background:var(--paper);color:var(--ink)}}'
        )
        # Keep small math scripts readable without overriding each block's own
        # title/heading/body size. The browser gate checks all remaining text.
        minimum_text_size = (
            "\nsection.page .katex,section.page .katex *,"
            "section.page sup,section.page sub {font-size:8pt!important}\n"
        )
        css = (font_face_css(chosen_fonts) + "\n" + theme + "\n" + str(reply.css or "")
               + minimum_text_size)
        raw_spec.update({
            "mode": "backbone", "seed": spec.design_seed, "draws": {}, "params": {},
            "content_id": spec.content_id, "layout_plan": layout_plan,
            "brief": getattr(agent, "current_design_brief", {}), "table_frame_type": table_frame,
        })
        raw_spec.setdefault("layout", {"details": {"summary": (raw_spec.get("brief") or {}).get("grid", "")}})
        raw_spec.setdefault("reading_order", {"details": {"rule": "measured region geometry"}})
        raw_spec.setdefault("orientation", {"details": {"rule": "size per layout role"}})
        html = build_design(
            spec.doc_type, lang, content.config.design.get("fixed_labels", {}), css, {}, None,
            layout_plan=layout_plan, content_config=content.config,
        )
    else:
        rounded_draws = {
            name: [round(value, 4) for value in values]
            for name, values in draws(spec.design_seed).items()
        }
        raw_spec["seed"] = spec.design_seed
        raw_spec["draws"] = rounded_draws
        pages = {role: dict(choice) if isinstance(choice, dict) else {}
                 for role, choice in (reply.pages or {}).items()}
        params = agent.design_params(spec.design_seed) if hasattr(agent, "design_params") else draw_params(spec.design_seed)
        # "skipped" is the model's bookkeeping; drop entries that do not match a chosen index instead of failing.
        raw_spec["skipped"] = [row for row in raw_spec.get("skipped") or []
                               if isinstance(row, dict) and row.get("reason") and row.get("criterion") in raw_spec
                               and row.get("index") == (raw_spec.get(row["criterion"]) or {}).get("index")]
        raw_spec["params"] = params
        # Orientation is drawn by code (params.size_plan); record it in the same criterion shape.
        raw_spec["orientation"] = {
            "options": list(SIZE_PLANS), "index": list(SIZE_PLANS).index(params["size_plan"]),
            "chosen": params["size_plan"], "details": {"source": "code", "rule": "sheet sizes drawn by code"},
        }
        html = build_design(spec.doc_type, lang, content.config.design.get("fixed_labels", {}), reply.css, pages, params)
    html, corrections = tidy_design(
        html, content.config, agent.ctx.taxonomy, spec.design_seed, table_frame=table_frame,
    )
    if corrections:
        log(f"design: fixed {len(corrections)} attribute spelling(s) locally", spec.doc_id)
        agent.ctx.trace.events.append(TraceEvent(
            time=datetime.now(timezone.utc), stage="design", kind="check", detail={"tidy_corrections": corrections[:50]},
        ))
    design_dir = target / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / "design.html").write_text(html, encoding="utf-8")
    orientation = dict(raw_spec.get("orientation") or {})
    orientation["pages"] = page_sizes(html)
    raw_spec["orientation"] = orientation
    design_spec = DesignSpec.model_validate(raw_spec)
    (design_dir / "design_spec.json").write_text(
        design_spec.model_dump_json(indent=2) + "\n", encoding="utf-8",
    )

    problems = orientation_problems(html, design_spec)
    root = parse_html(html)
    forbidden = content.config.design.get("forbidden_words", [])
    forbidden = {str(word).casefold() for word in forbidden}
    for node in root.walk():
        if "data-label" not in node.attrs:
            continue
        text = extract_text(node).casefold()
        for word in sorted(forbidden):
            if word and re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
                problems.append(f"forbidden static label word: {word}")
    try:
        validate_template(html, content.config, agent.ctx.taxonomy)
    except ValueError as exc:
        problems.extend(getattr(exc, "problems", [str(exc)]))
    doc = spec.doc_id
    if problems:
        log(f"design: rejected before fill, {len(problems)} problem(s)", doc)
        raise ValueError("\n".join(problems))

    log("fill: pouring content into the design", doc)
    render_content = content
    if backbone_mode and getattr(agent, 'current_direction', {}).get('heading') == 'numbered':
        from copy import deepcopy
        render_content = deepcopy(content)
        counters = [0,0,0]
        for element in render_content.values['body']:
            if element['type'] != 'heading': continue
            level=element['level']; counters[level-1]+=1
            for i in range(level,3): counters[i]=0
            if not re.match(r'\s*\d',element['text']):
                label='.'.join(str(n) for n in counters[:level])+'. '
                element['resolved_spans']=[{'type':'text','text':label}]+element['resolved_spans']
    result = await fill(html, render_content, spec, agent.ctx.taxonomy, agent.ctx.browser)
    result.trace = agent.ctx.trace
    write_bundle(result, target)
    # write_bundle does not own the blank-template sidecar.
    (design_dir / "design.html").write_text(html, encoding="utf-8")
    (design_dir / "design_spec.json").write_text(
        design_spec.model_dump_json(indent=2) + "\n", encoding="utf-8",
    )

    log(f"fill: {result.manifest.page_count} pages; running lint and design checks", doc)
    lint_issues = await lint_document(target, agent.ctx.browser, agent.ctx.taxonomy)
    spec_warnings: list[str] = []
    design_issues = check(target, agent.ledger_entries, spec_warnings)
    browser_issues = await browser_checks(
        target, agent.ctx.browser, min_font_px=10.66 if backbone_mode else 9,
    )
    geometry_issues = []
    if backbone_mode:
        from factory.design.checks import check_backbone_geometry
        geometry_issues = await check_backbone_geometry(
            target, layout_plan, content.config, agent.ctx.browser,
        )
    if backbone_mode and getattr(agent, 'current_direction', None):
        from factory.design.direction import check_rendered
        geometry_issues += await check_rendered(target, agent.current_direction, agent.ctx.browser)
    fills = await page_fill(target, result.manifest, agent.ctx.browser)
    warnings = spec_warnings + [
        f"page {page['index']}: body fill {page['fill']:.1%} below 20%"
        for page in fills if page["body_eligible"] and page["fill"] < 0.2
    ]
    agent.ctx.trace.events.append(TraceEvent(
        time=datetime.now(timezone.utc), stage="design", kind="check",
        detail={"page_fill": fills, "warnings": warnings,
                "issues": [str(issue) for issue in lint_issues] + design_issues + browser_issues + geometry_issues},
    ))
    issues = [str(issue) for issue in lint_issues] + design_issues + browser_issues + geometry_issues
    log(f"checks: {len(lint_issues)} lint, {len(design_issues)} design, {len(browser_issues)} browser, "
        f"{len(geometry_issues)} geometry issue(s)"
        + (f", {len(warnings)} warning(s)" if warnings else ""), doc)
    image_dir = target / "images"
    image_dir.mkdir(exist_ok=True)
    for page in result.manifest.pages:
        image_path = image_dir / f"page_{page.index:03}.png"
        image_path.write_bytes(await agent.ctx.browser.render(target / page.file, dpi=200))
    if issues:
        raise ValueError("\n".join(issues))
    if backbone_mode and getattr(agent, 'current_direction', None):
        from factory.design.novelty import fingerprint, measure, nearest, same_content_conflict
        import yaml
        fp = fingerprint(layout_plan, agent.current_direction, await measure(target, agent.ctx.browser))
        archive = [r.get('design_spec',r) for r in agent.ledger_entries]
        neighbour = nearest(fp, archive)
        minimum = yaml.safe_load((ROOT/'configs/design.yaml').read_text(encoding='utf-8')).get('novelty',{}).get('struct_min',0.15)
        if neighbour and neighbour[0] < minimum:
            raise ValueError(f'structural novelty: nearest distance {neighbour[0]:.3f} below {minimum}')
        if same_content_conflict(spec.content_id, fp, archive):
            raise ValueError('structural novelty: same content already has this region arrangement')
        raw_spec['fingerprint'] = fp
        raw_spec['fingerprint']['nearest_distance'] = neighbour[0] if neighbour else None
        (design_dir / 'design_spec.json').write_text(
            DesignSpec.model_validate(raw_spec).model_dump_json(indent=2)+'\n', encoding='utf-8')
    result.trace.status = "ok"
    result.trace.finished = datetime.now(timezone.utc)
    return result
