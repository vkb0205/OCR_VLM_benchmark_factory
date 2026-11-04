"""Design stage as a tool-using coding agent.

The model writes the design, renders it, reads the same checks the pipeline enforces, inspects pages
(images and measured boxes) and edits its CSS until every check passes, then submits. Code still owns the
page structure and the final gate: `submit` is refused unless the latest render passed every check.
"""
import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from factory.contract.models.trace import TraceEvent
from factory.log import log, short

MAX_TURNS = 15
MAX_RESULT_CHARS = 9_000

INSTRUCTIONS = """You are the design engineer for this document and you work with tools.
Workflow: call apply_design with a full design (design_spec, css, pages); it builds, fills, paginates and runs every
check, then returns the problems. After that, change the CSS with replace_css (exact edits) or append_css (new
rules); apply_design's css always replaces the WHOLE stylesheet. Use view_pages to look at rendered pages and measure to read
boxes in mm before guessing. Fix causes, not symptoms: if a box overflows, read its size and content with measure first.
When apply_design reports that every check passes, look at a few pages (cover, a statement, the signature pages); fix
anything that looks wrong or unprofessional, then call submit. You have a limited number of turns; batch tool calls."""

TOOLS = [
    {"name": "apply_design",
     "description": "Set the design and render it. Omitted parts keep their current value. Returns the check result.",
     "parameters": {"type": "object", "properties": {
         "design_spec": {"type": "object", "description": "design_spec object as described in the task"},
         "css": {"type": "string", "description": "the COMPLETE stylesheet; it replaces the current one. "
                                                  "To change part of it use append_css or replace_css"},
         "pages": {"type": "object", "description": "per-role page choices as described in the task"}},
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


class DesignSession:
    def __init__(self, agent, content, spec, target: Path):
        self.agent, self.content, self.spec, self.target = agent, content, spec, target
        self.design = {"design_spec": {}, "css": "", "pages": {}}
        self.result = None  # render result of the latest passing render
        self.passed = False
        self.last_problems = "no design applied yet"
        self.page_count = 0
        self.failing_pages: list[int] = []

    async def render(self) -> str:
        from factory.agent import DesignReply
        from factory.design.agent import render_design

        self.agent.latest_design_reply = json.dumps(self.design, ensure_ascii=False)
        if self.target.exists():
            shutil.rmtree(self.target)
        self.target.mkdir(parents=True)
        self.passed, self.result = False, None
        try:
            reply = DesignReply.model_validate(self.design)
            self.result = await render_design(self.agent, self.content, self.spec, self.target, reply)
        except Exception as exc:
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
        checks = [e.detail for e in self.agent.ctx.trace.events if e.kind == "check" and "warnings" in (e.detail or {})]
        warnings = checks[-1]["warnings"] if checks else []
        notes = ("\nWarnings (not blocking, improve if you can): " + "; ".join(warnings)) if warnings else ""
        return (f"ALL CHECKS PASS. {self.page_count} pages ({roles}).{notes}\nLook at key pages, fix anything that "
                "looks wrong, then call submit.")

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
        if name == "apply_design":
            current, new = self.design["css"], args.get("css")
            if current and isinstance(new, str) and len(new) < 0.6 * len(current):
                return (f"Refused: css would replace the whole {len(current):,}-character stylesheet with "
                        f"{len(new):,} characters. Use append_css or replace_css for partial changes, "
                        "or send the complete stylesheet."), None
            for key in ("design_spec", "css", "pages"):
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
                return "Submitted.", None
            return "Refused: the latest render did not pass. Problems:\n" + _clip(self.last_problems), None
        return f"Unknown tool {name}.", None


async def design_with_tools(agent, content, spec, target: Path, *, max_turns: int = MAX_TURNS):
    """Run the design session; return the render result of the submitted design or raise with the last problems."""
    session = DesignSession(agent, content, spec, target)
    task = agent._design_prompt(content, spec).rsplit("\n", 1)[0]  # drop the JSON reply rule
    messages = [{"role": "system", "content": agent.system + "\n\n" + INSTRUCTIONS},
                {"role": "user", "content": task + "\n\nStart with apply_design."}]
    doc = spec.doc_id
    for turn in range(1, max_turns + 1):
        started = datetime.now(timezone.utc)
        reply = await agent.ctx.llm.tool_turn(agent.doc_type, messages, TOOLS)
        result = reply.result
        agent.ctx.trace.events.append(TraceEvent(
            time=datetime.now(timezone.utc), stage="design", kind="llm_call", provider=result.provider,
            model=result.model, tokens_in=result.tokens_in, tokens_out=result.tokens_out, cost_usd=result.cost_usd,
            detail={"call_kind": "design_agent", "turn": turn, "tools": [c.name for c in reply.calls]},
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
            if call.name == "submit" and session.passed:
                submitted = True
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
        if submitted:
            log(f"design agent: submitted after {turn} turn(s)", doc)
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
        return session.result
    raise ValueError(session.last_problems)
