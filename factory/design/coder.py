"""Design stage as a tool-using coding agent.

The model writes the design, renders it, reads the same checks the pipeline enforces, inspects pages
(images and measured boxes) and edits its CSS until every check passes, then submits. Code still owns the
page structure and the final gate: `submit` is refused unless the latest render passed every check.
"""
import io
import json
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import re

from pydantic import BaseModel, Field

from factory.contract.models.trace import TraceEvent
from factory.log import log, short

MAX_TURNS = 8
MAX_RESULT_CHARS = 9_000

SKILL_NAMES = (
    "academic_typography", "grids_and_regions", "tables", "title_blocks",
    "color_and_contrast", "vietnamese_typesetting", "design_brief",
)

SKILL_INDEX = """Skills available through read_skill:
- academic_typography: hierarchy, scale, measure, leading, and long-form text.
- grids_and_regions: layout_plan boxes, flows, chains, float spans, and code-owned frame.
- tables: frame types, numeric alignment, and wide-table treatment.
- title_blocks: required title-page fields and sizing from the profile.
- color_and_contrast: rendered 4.5:1 contrast and restrained print palettes.
- vietnamese_typesetting: registry coverage, diacritics, and line breaks.
- design_brief: a specific concept that explains its differences from neighbours.
"""

BACKBONE_WORKFLOW = """You design a new academic-paper layout and visual style for each document. Code owns only the required page roles, fields, frame, region primitives, and correctness gates. The content profile contains counts and lengths; never request, infer, or write paper prose.

The design process has two parts. First, write one JSON brief from the profile, the supplied archive neighbours, and the design_brief skill. Then turn that brief into a layout_plan, stylesheet, and design_spec with apply_design. The profile and archive are document-specific user input; this shared system prefix stays unchanged.

The layout_plan has exactly four role keys: title_page, body, references, appendix. Every role needs size, body_font_size_pt (at least 8), regions, flow, and float_defaults. Each region has name, ascending chain, and box {x,y,w,h}; dimensions use mm or %. The first region is named body. Flow lists the role's required slots and traverses every region chain in order. Keep each region inside main, at least 35 average characters wide, and do not overlap regions. Use several regions for columns; never use CSS columns. Floats must fit their declared span and stay whole. A wide_table_page, when needed, has one landscape region and min_columns.

Required slots: title_page = title, authors, affiliations, abstract, abstract_alt, keywords, keywords_alt, journal; body = body; references = references; appendix = acknowledgement. The title-page journal slot is a code-owned header slot, so omit it from that role's flow list. Optional fields remain optional and every field is placed once by code. Fixed labels, headers, footers, page numbers, main, regions, and structural attributes are code-owned. CSS may style the frame but cannot move or resize it or any region.

Choose two family names from the supplied font registry for heading and body roles. Put them in design_spec.style.fonts. Put three or more #RRGGBB colors in design_spec.style.palette in paper/background, ink, accent order. Choose a valid table_frame_type: full_line, less_line, fewer_line, or wireless_line. Record leading, body font size, margins, font roles, and material treatment in design_spec. The code generates @font-face rules from the selected registry families. Do not use params.py values or invent a font catalogue.

Use read_skill when you need the relevant principles. Then apply the design, inspect the title page, a body page with a multi-region float when one exists, and the first references page with view_pages, and only then submit. Fix small fit or contrast problems through tidy before asking the agent to revise. Keep every visible text run, including nested math and table text, at least 8 pt; rendered contrast must be at least 4.5:1. Do not use text-transform, because visible text must match source text exactly. Avoid overlap, clipping, external URLs, CSS-generated text, and invented paper content.

""" + SKILL_INDEX


@lru_cache(maxsize=1)
def _backbone_shared_prefix() -> str:
    from factory.design.backbone import load_backbone
    from factory.design.fonts import registry

    backbone = load_backbone()
    contract = {
        "allowed_sizes": backbone["allowed_sizes"],
        "page_roles": backbone["page_roles"],
        "frame": backbone["frame"],
        "limits": backbone["limits"],
        "font_registry": [{"name": item.name, "classification": item.classification}
                           for item in registry()],
    }
    from factory.content.config import load_config
    shared = load_config().system.strip()
    return shared + "\n\n" + BACKBONE_WORKFLOW + "\nBackbone contract:\n" + json.dumps(
        contract, ensure_ascii=False, separators=(",", ":"),
    )


class DesignBrief(BaseModel):
    concept: str
    grid: str
    typography_density: str
    colour_rules_ornament: str
    title_block: str
    table_figure_treatment: str
    differences: list[dict[str, str]] = Field(default_factory=list)


def _word_count(brief: DesignBrief) -> int:
    parts = [brief.concept, brief.grid, brief.typography_density, brief.colour_rules_ornament,
             brief.title_block, brief.table_figure_treatment]
    parts.extend(" ".join(row.values()) for row in brief.differences)
    return len(re.findall(r"\b[\w’'-]+\b", " ".join(parts)))

INSTRUCTIONS = """You are the design engineer for this document and you work with tools.
Workflow: call apply_design with a full design (design_spec, css, pages); it builds, fills, paginates and runs every
check, then returns the problems. After that, change the CSS with replace_css (exact edits) or append_css (new
rules); apply_design's css always replaces the WHOLE stylesheet. Use view_pages to look at rendered pages and measure to read
boxes in mm before guessing. Fix causes, not symptoms: if a box overflows, read its size and content with measure first.
When apply_design reports that every check passes, look at a few pages (cover, a statement, the signature pages); fix
anything that looks wrong or unprofessional, then call submit. You have a limited number of turns; batch tool calls."""

TOOLS = [
    {"name": "read_skill", "description": "Load one design-principle skill file by name.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string", "enum": list(SKILL_NAMES)}},
         "required": ["name"], "additionalProperties": False}},
    {"name": "apply_design",
     "description": "Set the design and render it. Omitted parts keep their current value. Returns the check result.",
     "parameters": {"type": "object", "properties": {
         "design_spec": {"type": "object", "description": "design_spec object as described in the task"},
         "css": {"type": "string", "description": "the COMPLETE stylesheet; it replaces the current one. "
                                                  "To change part of it use append_css or replace_css"},
         "pages": {"type": "object", "description": "legacy per-role page choices"},
         "layout_plan": {"type": "object", "description": "layout_plan for the code-owned academic backbone"}},
         "additionalProperties": False}},
    {"name": "replace_css",
     "description": "Replace exact text in the current CSS (each find must occur once), then render and check.",
     "parameters": {"type": "object", "properties": {
         "edits": {"type": "array", "items": {"type": "object", "properties": {
             "find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["find", "replace"]}}},
         "required": ["edits"], "additionalProperties": False}},
    {"name": "append_css",
     "description": "Append rules to the end of the current CSS (later rules win), then render and check.",
     "parameters": {"type": "object", "properties": {"css": {"type": "string"}},
                    "required": ["css"], "additionalProperties": False}},
    {"name": "view_pages",
     "description": "Images of rendered pages (1-based numbers, up to 4) from the latest render.",
     "parameters": {"type": "object", "properties": {
         "pages": {"type": "array", "items": {"type": "integer"}, "maxItems": 4}},
         "required": ["pages"], "additionalProperties": False}},
    {"name": "measure",
     "description": "Boxes (mm, relative to the page) and key computed styles of elements matching a CSS selector "
                    "on a rendered page, up to 12 elements.",
     "parameters": {"type": "object", "properties": {
         "page": {"type": "integer"}, "selector": {"type": "string"}},
         "required": ["page", "selector"], "additionalProperties": False}},
    {"name": "show_css", "description": "The current stylesheet.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "submit", "description": "Finish. Refused unless the latest render passed every check.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]

MEASURE = """([selector]) => {
  const mm = v => Math.round(v * 25.4 / 96 * 10) / 10, body = document.body.getBoundingClientRect();
  let nodes;
  try { nodes = [...document.querySelectorAll(selector)]; } catch (e) { return {error: String(e)}; }
  return {count: nodes.length, page_mm: [mm(body.width), mm(body.height)], elements: nodes.slice(0, 12).map(e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return {tag: e.tagName.toLowerCase(), cls: String(e.className || ''), slot: e.dataset.slot || e.dataset.block || '',
            x: mm(r.x - body.x), y: mm(r.y - body.y), w: mm(r.width), h: mm(r.height),
            scroll_h: mm(e.scrollHeight), client_h: mm(e.clientHeight),
            style: {position: s.position, display: s.display, height: s.height, max_height: s.maxHeight,
                    min_height: s.minHeight, overflow: s.overflow, font_size: s.fontSize, color: s.color,
                    background: s.backgroundColor},
            text: (e.innerText || '').trim().slice(0, 80)};
  })};
}"""


DIAGNOSE = """([ids]) => {
  const mm = v => Math.round(v * 25.4 / 96 * 10) / 10, body = document.body.getBoundingClientRect(), out = {};
  const sheets = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } });
  for (const id of ids) {
    const e = document.querySelector(`[data-gt-id="${id}"]`) ||
              [...document.querySelectorAll('*')].find(n => (n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).split(' ').join('.') : '')) === id);
    if (!e) continue;
    const box = n => { const r = n.getBoundingClientRect(); return [mm(r.x - body.x), mm(r.y - body.y), mm(r.width), mm(r.height)]; };
    const rules = sheets.filter(r => r.selectorText && (() => { try { return e.matches(r.selectorText); } catch (x) { return false; } })())
      .map(r => r.cssText).filter(t => !t.startsWith('section.page') && !t.startsWith('*')).slice(-6);
    out[id] = {box_xywh_mm: box(e), parent: e.parentElement ? [e.parentElement.tagName.toLowerCase() + '.' + String(e.parentElement.className || ''), box(e.parentElement)] : null,
               page_mm: [mm(body.width), mm(body.height)], your_matching_rules: rules,
               children_h_mm: [...e.children].slice(0, 10).map(c => [(c.dataset.slot || c.dataset.gtId ||
                 c.tagName.toLowerCase() + (c.className ? '.' + String(c.className).split(' ')[0] : '')), box(c)[3]])};
  }
  return out;
}"""


def _problem_targets(problems: list[str]) -> dict[int, list[str]]:
    """Page number -> element ids or tag.class names mentioned in check problems."""
    import re
    found: dict[int, list[str]] = {}
    for line in problems:
        page = re.search(r"page[ _](\d+)", line)
        if not page:
            continue
        names = re.findall(r"block (\S+?)[:\s]", line + " ") + re.findall(r"<([^>]+)>", line)
        names += re.findall(r"overlap: (\S+) / (\S+)", line)[0] if "overlap:" in line else []
        names += re.findall(r"contrast: (\S+)", line)
        found.setdefault(int(page[1]), [])
        found[int(page[1])] += [n for n in names if n not in found[int(page[1])]]
    return found


def _clip(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "\n… (truncated)"


def _page_image(target: Path, numbers: list[int]) -> bytes | None:
    from PIL import Image
    paths = [target / "images" / f"page_{n:03}.png" for n in numbers]
    images = [Image.open(p).convert("RGB") for p in paths if p.is_file()]
    if not images:
        return None
    for image in images:
        image.thumbnail((900, 900) if len(images) == 1 else (600, 600))
    sheet = Image.new("RGB", (sum(i.width for i in images) + 10 * (len(images) - 1), max(i.height for i in images)),
                      "white")
    x = 0
    for image in images:
        sheet.paste(image, (x, 0))
        x += image.width + 10
    out = io.BytesIO()
    sheet.save(out, format="PNG")
    return out.getvalue()


def _paper_profile(agent, content, spec) -> dict:
    from factory.content.profile import profile

    variables = dict(agent.variables)
    variables.setdefault("lang", content.lang or agent.lang)
    return profile({"values": content.values, "variables": variables, "content_id": spec.content_id})


def _archive_neighbours(agent) -> list[dict]:
    from factory.design.ledger import summary

    rows = agent.ledger_entries
    selected = rows[-8:]
    return [{"doc_id": row.get("doc_id", "?"), "summary": summary(row)} for row in selected]


async def _make_brief(agent, content, spec, profile: dict, neighbours: list[dict]) -> DesignBrief:
    skill_path = Path(__file__).resolve().parent / "skills" / "design_brief.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    task = "\n".join((
        f"Create a 150–300 word design brief for document {spec.doc_id}. Count words by spaces. Keep the six main fields concise; each should be about 20–35 words. Each neighbour difference is one sentence of at most 15 words.",
        "The content profile and neighbour summaries are metadata only; do not invent or repeat prose.",
        "Return one JSON object with keys concept, grid, typography_density, colour_rules_ornament, ",
        "title_block, table_figure_treatment, and differences.",
        "differences is an array with one object per supplied neighbour: {doc_id, sentence}.",
        "Use the supplied design_brief skill.",
        "DESIGN BRIEF SKILL:\n" + skill_text,
        "CONTENT PROFILE:\n" + json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
        "ARCHIVE NEIGHBOURS:\n" + json.dumps(neighbours, ensure_ascii=False, separators=(",", ":")),
    ))
    messages = [{"role": "system", "content": _backbone_shared_prefix()},
                {"role": "user", "content": task}]
    started = datetime.now(timezone.utc)
    result = await agent.ctx.llm.generate(agent.doc_type, messages)
    agent.ctx.trace.events.append(TraceEvent(
        time=datetime.now(timezone.utc), stage="brief", kind="llm_call", provider=result.provider,
        model=result.model, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
        tokens_cached=result.tokens_cached, tokens_reasoning=result.tokens_reasoning, cost_usd=result.cost_usd,
        detail={"call_kind": "design_brief", "cached": result.cached,
                "tokens_cached": result.tokens_cached, "tokens_reasoning": result.tokens_reasoning,
                "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3)},
    ))
    from factory.llm.client import parse_json
    brief = DesignBrief.model_validate(parse_json(result.text, DesignBrief))
    word_count = _word_count(brief)
    agent.ctx.trace.events[-1].detail["brief_word_count"] = word_count
    if not 150 <= word_count <= 300:
        raise ValueError(f"design brief has {word_count} words; expected 150–300")
    agent.current_design_brief = brief.model_dump(mode="json")
    agent.current_content_profile = profile
    agent.current_neighbours = neighbours
    log(f"design brief: {word_count} words; {result.tokens_cached:,} cached input tokens", spec.doc_id)
    return brief


def _backbone_build_task(spec, profile: dict, brief: DesignBrief, neighbours: list[dict]) -> str:
    return "\n\n".join((
        f"Implement the design brief for academic-paper document {spec.doc_id} (seed {spec.design_seed}).",
        "PROFILE (no paper prose):\n" + json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
        "YOUR DESIGN BRIEF:\n" + brief.model_dump_json(),
        "ARCHIVE NEIGHBOURS:\n" + json.dumps(neighbours, ensure_ascii=False, separators=(",", ":")),
        "Use read_skill for the grid, typography, title-block, table, contrast, or Vietnamese principles needed.",
        "Call apply_design with a complete layout_plan, css, and design_spec. For design_spec include:",
        '{"layout":{"details":{"summary":"..."}},"style":{"palette":["#paper","#ink","#accent"],'
        '"fonts":["heading family","body family"],"details":{"body_font_size_pt":10,"leading":1.3,'
        '"margins_mm":15,"summary":"..."}},"reading_order":{"details":{"rule":"..."}},'
        '"orientation":{"details":{"rule":"..."}},"table_frame_type":"less_line"}.',
        "Choose both fonts from the names listed in the system registry. Choose a frame from the four allowed values.",
        "Use CSS variables --font-head, --font-body, --paper, --ink, --accent, --base-size, and --margin. "
        "Do not define @font-face, external URLs, CSS columns, fixed heights for flowing text or tables, or content: text.",
        "Use each page role's exact slot flow and place no visible text. Code generates the page frame and labels.",
        "After the checks pass, call view_pages for the required pages listed by apply_design, correct any visual issue, then submit.",
        "Begin with relevant read_skill calls, then apply_design.",
    ))


class DesignSession:
    def __init__(self, agent, content, spec, target: Path, *, brief: dict | None = None):
        self.agent, self.content, self.spec, self.target = agent, content, spec, target
        self.design = {"design_spec": {}, "css": "", "pages": {}, "layout_plan": {}}
        self.brief = brief or {}
        self.result = None  # render result of the latest passing render
        self.passed = False
        self.last_passing_result = None
        self.last_passing_reply = None
        self.last_problems = "no design applied yet"
        self.page_count = 0
        self.failing_pages: list[int] = []
        self.required_inspection_pages: list[int] = []
        self.viewed_pages: set[int] = set()
        self.backbone = content.config.design.get("mode") == "backbone"

    async def render(self) -> str:
        from factory.agent import DesignReply
        from factory.design.agent import render_design

        self.passed, self.result = False, None
        self.required_inspection_pages, self.viewed_pages = [], set()

        async def render_once():
            self.agent.latest_design_reply = json.dumps(
                {**self.design, "brief": self.brief}, ensure_ascii=False,
            )
            if self.target.exists():
                shutil.rmtree(self.target)
            self.target.mkdir(parents=True)
            reply = DesignReply.model_validate(self.design)
            return await render_design(self.agent, self.content, self.spec, self.target, reply)

        caught = None
        try:
            self.result = await render_once()
        except Exception as exc:
            caught = exc
            if self.backbone:
                from factory.design.tidy import tidy_backbone_css
                adjusted_css, corrections = await tidy_backbone_css(
                    self.target, self.agent.ctx.browser, self.design.get("css", ""),
                )
                if corrections:
                    self.design["css"] = adjusted_css
                    self.agent.ctx.trace.events.append(TraceEvent(
                        time=datetime.now(timezone.utc), stage="design", kind="check",
                        detail={"tidy_corrections": corrections},
                    ))
                    log(f"tidy: applied {len(corrections)} small mechanical correction(s)", self.spec.doc_id)
                    try:
                        self.result = await render_once()
                    except Exception as adjusted_exc:
                        caught = adjusted_exc
                    else:
                        caught = None
        if caught is None and self.result is not None:
            self.last_passing_result = self.result
            self.last_passing_reply = self.agent.latest_design_reply
            backup = self.target.parent / (self.target.name + '_last_passing')
            if backup.exists(): shutil.rmtree(backup)
            shutil.copytree(self.target, backup)
        if caught is not None:
            exc = caught
            problems = getattr(exc, "problems", None) or str(exc).splitlines()
            self.last_problems = "\n".join(str(p) for p in problems)
            await self._keep_failing_pages(exc)
            images = sorted((self.target / "images").glob("page_*.png"))
            self.page_count = len(images)
            rendered = f"{len(images)} pages rendered; " if images else "nothing rendered (failed before pages); "
            report = f"CHECKS FAILED ({rendered}{len(problems)} problem(s)):\n" + self.last_problems
            self.failing_pages = []
            try:
                diagnosis = {}
                for number, names in list(_problem_targets([str(p) for p in problems]).items())[:3]:
                    path = self.target / "pages" / f"page_{number:03}.html"
                    if names and path.is_file():
                        async with self.agent.ctx.browser.page(path) as (page, _b, _f):
                            diagnosis[f"page {number}"] = await page.evaluate(DIAGNOSE, [names[:6]])
                    self.failing_pages.append(number)
                if diagnosis:
                    report = _clip(report)[:4000] + "\nDIAGNOSIS (boxes x,y,w,h in mm; the rules of yours that apply):\n" + \
                        json.dumps(diagnosis, ensure_ascii=False)
            except Exception as exc:  # diagnosis is a help, never a blocker
                log(f"design agent: diagnosis failed: {short(exc, 120)}", self.spec.doc_id)
            return _clip(report)
        self.passed = True
        self.page_count = self.result.manifest.page_count
        roles = ", ".join(f"{p.index}:{p.role}" for p in self.result.manifest.pages)
        if self.backbone:
            self.required_inspection_pages = await self._inspection_pages()
            self.viewed_pages = set()
        checks = [e.detail for e in self.agent.ctx.trace.events if e.kind == "check" and "warnings" in (e.detail or {})]
        warnings = checks[-1]["warnings"] if checks else []
        notes = ("\nWarnings (not blocking, improve if you can): " + "; ".join(warnings)) if warnings else ""
        required = (f" Required inspection pages before submit: {self.required_inspection_pages}."
                    if self.backbone else "")
        return (f"ALL CHECKS PASS. {self.page_count} pages ({roles}).{required}{notes}\nLook at key pages, fix anything that "
                "looks wrong, then call submit.")

    async def _inspection_pages(self) -> list[int]:
        from factory.contract.extract import parse_html

        pages = self.result.manifest.pages
        required = []
        title = next((page.index for page in pages if page.role == "title_page"), None)
        references = next((page.index for page in pages if page.role == "references"), None)
        if title:
            required.append(title)
        layout = self.design.get("layout_plan") or {}
        body_plan = (layout.get("roles") or {}).get("body") or {}
        span = (body_plan.get("float_defaults") or {}).get("span", 1)
        if span > 1:
            for entry in pages:
                if entry.role != "body":
                    continue
                path = self.target / entry.file
                root = parse_html(path.read_text(encoding="utf-8"))
                if any(int(node.attrs.get("data-float-span", "1")) > 1
                       for node in root.walk() if node.attrs.get("data-float-span", "1").isdigit()):
                    required.append(entry.index)
                    break
        if references:
            required.append(references)
        return list(dict.fromkeys(required))

    async def _keep_failing_pages(self, exc) -> None:
        """Fill failures carry their failing pages; write and render them so they can be viewed and measured."""
        pages, assets = getattr(exc, "pages", None), getattr(exc, "assets", None)
        if not pages:
            return
        for name, data in (assets or {}).items():
            path = self.target / "assets" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.target / "pages").mkdir(exist_ok=True)
        (self.target / "images").mkdir(exist_ok=True)
        for number, html in pages.items():
            page_path = self.target / "pages" / f"page_{number:03}.html"
            page_path.write_text(html, encoding="utf-8")
            image = await self.agent.ctx.browser.render(page_path, dpi=96)
            (self.target / "images" / f"page_{number:03}.png").write_bytes(image)

    async def call(self, name: str, args: dict) -> tuple[str, bytes | None]:
        text, image = await self._call(name, args)
        if name in ("apply_design", "replace_css", "append_css") and not self.passed and self.failing_pages:
            image = image or _page_image(self.target, self.failing_pages[:2])
            if image:
                text += f"\nImages of failing pages {self.failing_pages[:2]} follow."
        return text, image

    async def _call(self, name: str, args: dict) -> tuple[str, bytes | None]:
        if "_invalid_json" in args:
            return "Your tool arguments were not valid JSON; send them again.", None
        if name == "read_skill":
            skill = str(args.get("name", ""))
            if skill not in SKILL_NAMES:
                return f"Unknown skill {skill!r}. Available: {', '.join(SKILL_NAMES)}", None
            path = Path(__file__).resolve().parent / "skills" / f"{skill}.md"
            if not path.is_file():
                return f"Skill file is missing: {skill}", None
            text = path.read_text(encoding="utf-8")
            self.agent.ctx.trace.events.append(TraceEvent(
                time=datetime.now(timezone.utc), stage="design", kind="tool_call",
                detail={"tool": "read_skill", "skill": skill},
            ))
            return text, None
        if name == "apply_design":
            current, new = self.design["css"], args.get("css")
            if current and isinstance(new, str) and len(new) < 0.6 * len(current):
                return (f"Refused: css would replace the whole {len(current):,}-character stylesheet with "
                        f"{len(new):,} characters. Use append_css or replace_css for partial changes, "
                        "or send the complete stylesheet."), None
            for key in ("design_spec", "css", "pages", "layout_plan"):
                if key in args:
                    self.design[key] = args[key]
            return await self.render(), None
        if name == "replace_css":
            css = self.design["css"]
            for edit in args.get("edits", []):
                found = css.count(edit.get("find", ""))
                if not edit.get("find") or found != 1:
                    return f"replace_css: {edit.get('find', '')[:80]!r} occurs {found} times; nothing changed.", None
                css = css.replace(edit["find"], edit["replace"])
            self.design["css"] = css
            return await self.render(), None
        if name == "append_css":
            self.design["css"] = self.design["css"] + "\n" + str(args.get("css", ""))
            return await self.render(), None
        if name == "view_pages":
            numbers = [n for n in args.get("pages", []) if isinstance(n, int)][:4]
            image = _page_image(self.target, numbers)
            if image is None:
                return f"No images for pages {numbers}; the latest render has {self.page_count} page images.", None
            self.viewed_pages.update(
                number for number in numbers
                if (self.target / "images" / f"page_{number:03}.png").is_file()
            )
            return f"Images of pages {numbers} follow in the next message.", image
        if name == "measure":
            path = self.target / "pages" / f"page_{int(args.get('page', 0)):03}.html"
            if not path.is_file():
                return f"No rendered page {args.get('page')}; the latest render has {self.page_count} pages.", None
            async with self.agent.ctx.browser.page(path) as (page, _blocked, _failed):
                found = await page.evaluate(MEASURE, [args.get("selector", "")])
            return _clip(json.dumps(found, ensure_ascii=False)), None
        if name == "show_css":
            return _clip(self.design["css"] or "(empty)"), None
        if name == "submit":
            if self.passed:
                missing = sorted(set(self.required_inspection_pages) - self.viewed_pages)
                if missing:
                    return f"Refused: inspect required page(s) {missing} with view_pages before submitting.", None
                return "Submitted.", None
            return "Refused: the latest render did not pass. Problems:\n" + _clip(self.last_problems), None
        return f"Unknown tool {name}.", None


async def design_with_tools(agent, content, spec, target: Path, *, max_turns: int = MAX_TURNS):
    """Run the design session; return the render result of the submitted design or raise with the last problems."""
    backbone = content.config.design.get("mode") == "backbone"
    if backbone:
        profile = _paper_profile(agent, content, spec)
        neighbours = _archive_neighbours(agent)
        from factory.design.direction import draw, build as build_direction
        direction = draw(spec.design_seed, agent.ledger_entries, config=content.config, content_id=spec.content_id)
        agent.current_direction = direction
        starting_plan, starting_css = build_direction(direction, content.config)
        profile = {**profile, 'hard_design_direction': direction}
        brief = await _make_brief(agent, content, spec, profile, neighbours)
        session = DesignSession(agent, content, spec, target, brief=brief.model_dump(mode="json"))
        task = _backbone_build_task(spec, profile, brief, neighbours)
        session.design.update(layout_plan=starting_plan, css=starting_css,
            design_spec={'direction':direction,'style':{'fonts':direction['fonts'],
                'palette':['#ffffff','#222222',direction['accent']], 'details':{'leading':direction['leading']}},
                'table_frame_type': 'full_line' if direction['table']=='grid' else 'less_line'})
        await session.render()
        task += "\nBudget: eight tool turns, including all page inspections. Batch related tool calls and refine the passing starting design. Submit as soon as required pages are inspected." 
        task += "\nHARD DIRECTION (preserve every axis):\n" + json.dumps(direction)
        task += "\nCODE-BUILT STARTING DESIGN (refine this):\n" + json.dumps(session.design)
        system = _backbone_shared_prefix()
    else:
        session = DesignSession(agent, content, spec, target)
        task = agent._design_prompt(content, spec).rsplit("\n", 1)[0]  # drop the JSON reply rule
        system = agent.system + "\n\n" + INSTRUCTIONS
    opening = "Begin by reading the relevant skills." if backbone else "Start with apply_design."
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task + "\n\n" + opening}]
    doc = spec.doc_id
    for turn in range(1, max_turns + 1):
        started = datetime.now(timezone.utc)
        reply = await agent.ctx.llm.tool_turn(agent.doc_type, messages, TOOLS)
        result = reply.result
        agent.ctx.trace.events.append(TraceEvent(
            time=datetime.now(timezone.utc), stage="design", kind="llm_call", provider=result.provider,
            model=result.model, tokens_in=result.tokens_in, tokens_out=result.tokens_out, cost_usd=result.cost_usd,
            tokens_cached=result.tokens_cached, tokens_reasoning=result.tokens_reasoning,
            detail={"call_kind": "design_agent", "turn": turn, "tools": [c.name for c in reply.calls],
                    "tokens_cached": result.tokens_cached, "tokens_reasoning": result.tokens_reasoning},
        ))
        log(f"design agent turn {turn}/{max_turns}: {', '.join(c.name for c in reply.calls) or 'no tool call'} "
            f"({result.tokens_in:,} in / {result.tokens_out:,} out, "
            f"{(datetime.now(timezone.utc) - started).total_seconds():.0f}s)", doc)
        messages.append(reply.message)
        if not reply.calls:
            messages.append({"role": "user", "content": "Use the tools: fix the design with apply_design or "
                                                        "replace_css, and call submit once every check passes."})
            continue
        images, submitted = [], False
        for call in reply.calls:
            try:
                text, image = await session.call(call.name, call.arguments)
            except Exception as exc:
                text, image = f"{call.name} failed: {short(exc, 300)}", None
            if image:
                images.append(image)
            if call.name == "submit" and text == "Submitted.":
                submitted = True
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
        if submitted:
            log(f"design agent: submitted after {turn} turn(s)", doc)
            backup = session.target.parent / (session.target.name + "_last_passing")
            if backup.exists(): shutil.rmtree(backup)
            return session.result
        if images:
            from factory.llm.client import _attach_images
            endpoint = agent.ctx.llm.endpoint(agent.doc_type)
            messages = _attach_images(messages + [{"role": "user", "content": "Requested page images:"}],
                                      endpoint.api, images)
        if turn == max_turns - 1:
            messages.append({"role": "user", "content": "One turn left: make your final fix now. If checks pass, "
                                                        "call submit in the same turn."})
    if session.passed:
        log("design agent: out of turns with a passing design; accepting it", doc)
        backup = session.target.parent / (session.target.name + "_last_passing")
        if backup.exists(): shutil.rmtree(backup)
        return session.result

    if session.last_passing_result is not None:
        backup = session.target.parent / (session.target.name + '_last_passing')
        if session.target.exists(): shutil.rmtree(session.target)
        shutil.copytree(backup, session.target)
        shutil.rmtree(backup)
        agent.latest_design_reply = session.last_passing_reply
        return session.last_passing_result
    raise ValueError(session.last_problems)
