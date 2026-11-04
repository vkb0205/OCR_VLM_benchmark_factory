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
    rounded_draws = {
        name: [round(value, 4) for value in values]
        for name, values in draws(spec.design_seed).items()
    }
    raw_spec["seed"] = spec.design_seed
    raw_spec["draws"] = rounded_draws
    lang = content.lang or spec.lang
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
    html, corrections = tidy_design(html, content.config, agent.ctx.taxonomy, spec.design_seed)
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
    result = await fill(html, content, spec, agent.ctx.taxonomy, agent.ctx.browser)
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
    design_issues = check(target, agent.ledger_entries[-4:], spec_warnings)
    browser_issues = await browser_checks(target, agent.ctx.browser)
    fills = await page_fill(target, result.manifest, agent.ctx.browser)
    warnings = spec_warnings + [
        f"page {page['index']}: body fill {page['fill']:.1%} below 20%"
        for page in fills if page["body_eligible"] and page["fill"] < 0.2
    ]
    agent.ctx.trace.events.append(TraceEvent(
        time=datetime.now(timezone.utc), stage="design", kind="check",
        detail={"page_fill": fills, "warnings": warnings,
                "issues": [str(issue) for issue in lint_issues] + design_issues + browser_issues},
    ))
    issues = [str(issue) for issue in lint_issues] + design_issues + browser_issues
    log(f"checks: {len(lint_issues)} lint, {len(design_issues)} design, {len(browser_issues)} browser issue(s)"
        + (f", {len(warnings)} warning(s)" if warnings else ""), doc)
    image_dir = target / "images"
    image_dir.mkdir(exist_ok=True)
    for page in result.manifest.pages:
        image_path = image_dir / f"page_{page.index:03}.png"
        image_path.write_bytes(await agent.ctx.browser.render(target / page.file, dpi=200))
    if issues:
        raise ValueError("\n".join(issues))
    result.trace.status = "ok"
    result.trace.finished = datetime.now(timezone.utc)
    return result
