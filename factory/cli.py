"""Command line entry point for Benchmark Factory."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from uuid import uuid4

from factory.design.coder import design_with_tools
from factory.agent import DESIGN_REPAIR_ROUNDS, DocumentAgent, JsonRepairFailure
from factory.browser.browser import Browser
from factory.content.config import load_config
from factory.content.language import choose_language
from factory.content.schema import validate_content
from factory.contract.lint import lint_document
from factory.contract.extract import parse_html
from factory.contract.models import (
    DesignCriterion,
    DesignSpec,
    DocSpec,
    DocumentRunRecord,
    LanguageStats,
    ProblemsRecord,
    RunRecord,
    SourceContent,
    Trace,
    TraceEvent,
)
from factory.contract.taxonomy import Taxonomy
from factory.design.agent import render_design
from factory.design.draws import design_seed
from factory.design.ledger import append as append_design, entries as design_entries, summary as ledger_summary
from factory.llm.client import Router
from factory.paths import ROOT
from factory.render.fill import fill, serialize
from factory.render.metrics import page_fill
from factory.render.contact import sheet
from factory.runner.context import Context
from factory.runner.dataset import rebuild_index, verify_output
from factory.runner.languages import stats
from factory.runner.layout import check_tree
from factory.runner.writer import write_bundle
from factory import log as progress
from factory.log import log, short


def gallery(output: Path) -> Path:
    """Rebuild the HTML gallery from accepted page images."""
    from html import escape

    cards = []
    for manifest_path in sorted((output / "documents").glob("*/*/document.json")):
        folder = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        images = []
        for page in manifest.get("pages", []):
            image = folder / "images" / f"page_{page['index']:03}.png"
            images.append(
                f'<img loading="lazy" width="240" src="{escape(image.relative_to(output).as_posix())}">'
            )
        cards.append(f"<article><h2>{escape(folder.name)}</h2>{''.join(images)}</article>")
    path = output / "gallery.html"
    path.write_text(
        '<!doctype html><meta charset="utf-8"><title>Factory gallery</title>' + "".join(cards),
        encoding="utf-8",
    )
    return path


def _default_design_spec(spec: DocSpec, html: str | None = None) -> DesignSpec:
    def criterion(choice: str, **extra):
        return DesignCriterion(
            options=[choice], index=0, chosen=choice,
            details={"source": "bundled template"}, **extra,
        )

    pages = {}
    if html:
        sections = [node for node in parse_html(html).walk()
                    if node.tag == "section" and "page" in node.attrs.get("class", "").split()]
        pages = {f"page_{index:03}": node.attrs.get("data-size", "")
                 for index, node in enumerate(sections, 1)}
    return DesignSpec(
        seed=spec.design_seed,
        draws={},
        layout=criterion("bundled default"),
        style=criterion(
            "bundled default", palette=["#ffffff", "#222222", "#315a78"],
            fonts=["Noto Serif", "Be Vietnam Pro"],
        ),
        reading_order=criterion("DOM order"),
        orientation=criterion("template pages", pages=pages),
    )


def _write_trace(path: Path, trace: Trace) -> None:
    path.write_text(trace.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _record(trace: Trace, doc_id: str, lang: str, status: str, seconds: float,
            failure_stage: str | None = None) -> DocumentRunRecord:
    return DocumentRunRecord(
        doc_id=doc_id,
        lang=lang,
        status=status,
        calls=sum(event.kind == "llm_call" for event in trace.events),
        tokens_in=sum(event.tokens_in or 0 for event in trace.events),
        tokens_out=sum(event.tokens_out or 0 for event in trace.events),
        cost_usd=round(sum(event.cost_usd or 0 for event in trace.events), 6),
        seconds=seconds,
        failure_stage=failure_stage,
    )


def _clean_tmp(output: Path) -> None:
    root = output / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()


async def _render_bundle_images(target: Path, manifest, browser) -> None:
    image_dir = target / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for page in manifest.pages:
        image = await browser.render(target / page.file, dpi=200)
        (image_dir / f"page_{page.index:03}.png").write_bytes(image)


def _save_failed(output: Path, spec: DocSpec, trace: Trace, stage: str, problem: Exception,
                 element_reply: str | None, design_reply: str | None, design_html: str | None,
                 source_content: SourceContent | None = None) -> None:
    folder = output / "failed" / spec.doc_type / spec.doc_id
    folder.mkdir(parents=True, exist_ok=True)
    trace.status = "failed"
    trace.finished = datetime.now(timezone.utc)
    trace.events.append(TraceEvent(
        time=trace.finished, stage=stage, kind="error", detail={"problem": str(problem)},
    ))
    (folder / "spec.json").write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _write_trace(folder / "trace.json", trace)
    if source_content is not None:  # accepted elements, so a design failure can be replayed offline
        (folder / "source_content.json").write_text(source_content.model_dump_json(indent=2) + "\n",
                                                    encoding="utf-8")
    problems = [line for line in str(problem).splitlines() if line.strip()] or [type(problem).__name__]
    (folder / "problems.json").write_text(
        ProblemsRecord(stage=stage, problems=problems).model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    replies = {}
    if element_reply:
        replies["element_reply.txt"] = element_reply
    if design_reply:
        replies["design_reply.txt"] = design_reply
    if replies:
        reply_dir = folder / "replies"
        reply_dir.mkdir(exist_ok=True)
        for name, content in replies.items():
            (reply_dir / name).write_text(content, encoding="utf-8")
    if design_html:
        design_dir = folder / "design"
        design_dir.mkdir(exist_ok=True)
        (design_dir / "design.html").write_text(design_html, encoding="utf-8")


def _clone_trace(source: Trace, doc_id: str) -> Trace:
    return Trace(
        doc_id=doc_id,
        factory_version=source.factory_version,
        started=source.started,
        events=[event.model_copy(deep=True) for event in source.events],
    )


def _spread_batch_call(items: list[dict], start_count: int) -> None:
    if not items:
        return
    first_trace = items[0]["agent"].ctx.trace
    if len(first_trace.events) <= start_count:
        return
    count = len(items)

    def share(value, index):
        value = value or 0
        quotient, remainder = divmod(value, count)
        return quotient + (1 if index < remainder else 0)

    added = list(enumerate(first_trace.events[start_count:], start_count))
    shared_repairs = sum(
        event.kind == "llm_call" and event.detail.get("call_kind") == "design_repair"
        for _, event in added
    )
    for event_index, event in added:
        if event.kind != "llm_call":
            continue
        shares = []
        for index in range(count):
            detail = dict(event.detail)
            if "estimated_tokens_in" in detail:
                detail["estimated_tokens_in"] = share(detail["estimated_tokens_in"], index)
            shares.append(event.model_copy(update={
                "tokens_in": share(event.tokens_in, index),
                "tokens_out": share(event.tokens_out, index),
                "cost_usd": (event.cost_usd or 0) / count,
                "detail": detail,
            }))
        first_trace.events[event_index] = shares[0]
        for item, call_event in zip(items[1:], shares[1:]):
            item["agent"].ctx.trace.events.append(call_event)
    for item in items[1:]:
        item["agent"]._call_counts["design_repair"] += shared_repairs


def _reset_stage(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _contact_images(target: Path, doc_id: str) -> list[bytes]:
    pages = sorted((target / "images").glob("page_*.png"))
    if not pages:
        return []
    contact_path = target.parent / f"contact_{doc_id}.png"
    try:
        sheet(pages, contact_path, columns=4, thumb=(320, 450))
        return [contact_path.read_bytes()]
    finally:
        contact_path.unlink(missing_ok=True)


async def _default_design(item: dict, browser, taxonomy):
    spec = item["spec"]
    content = item["content"]
    target = item["target"]
    template = ROOT / "designs" / spec.doc_type / "default.html"
    html = template.read_text(encoding="utf-8")
    if spec.doc_type == "academic_paper":
        root = parse_html(html)
        labels = content.config.design.get("fixed_labels", {}).get(content.lang or spec.lang, {})
        sections = [node for node in root.walk()
                    if node.tag == "section" and "page" in node.attrs.get("class", "").split()]
        for section in sections:
            role = section.attrs.get("data-page-role", "")
            nodes = [node for node in section.walk() if "data-label" in node.attrs]
            role_labels = labels.get(role, [])
            if len(nodes) != len(role_labels):
                raise ValueError(
                    f"academic_paper {role}: expected {len(nodes)} fixed labels, got {len(role_labels)}"
                )
            for node, label in zip(nodes, role_labels):
                node.children = [str(label)]
        html = serialize(root)
    result = await fill(html, content, spec, taxonomy, browser)
    result.trace = item["trace"]
    write_bundle(result, target)
    design_dir = target / "design"
    design_dir.mkdir(exist_ok=True)
    (design_dir / "design.html").write_text(html, encoding="utf-8")
    design_spec = _default_design_spec(spec, html)
    (design_dir / "design_spec.json").write_text(
        design_spec.model_dump_json(indent=2) + "\n", encoding="utf-8",
    )
    fills = await page_fill(target, result.manifest, browser)
    issues = await lint_document(target, browser, taxonomy)
    item["trace"].events.append(TraceEvent(
        time=datetime.now(timezone.utc), stage="check", kind="check",
        detail={"lint": [str(issue) for issue in issues], "page_fill": fills},
    ))
    if issues:
        raise ValueError("; ".join(str(issue) for issue in issues))
    await _render_bundle_images(target, result.manifest, browser)
    return result


async def _generate(a, output: Path, browser, taxonomy) -> int:
    run_started = datetime.now(timezone.utc)
    run_id = uuid4().hex
    output.mkdir(parents=True, exist_ok=True)
    for name in ("documents", "failed", "runs", "index", ".tmp"):
        (output / name).mkdir(exist_ok=True)
    _clean_tmp(output)

    config_catalog = load_config().documents
    if a.command == "redesign":
        raw = json.loads((a.path / "source_content.json").read_text(encoding="utf-8"))
        previous = DocSpec.model_validate_json((a.path / "spec.json").read_text(encoding="utf-8"))
        a.doc_type = previous.doc_type
        a.seed = previous.seed
        a.n = 1
        a.fixture = None
        a.lang = raw.get("lang") or raw.get("variables", {}).get("lang") or previous.lang
    else:
        raw = json.loads(a.fixture.read_text(encoding="utf-8")) if a.fixture else None
    if a.doc_type not in config_catalog:
        raise ValueError(f"Unknown document type: {a.doc_type}")

    router = Router(force=a.model) if not a.fixture or a.design in ("agent", "legacy") else None
    used_ids = []
    for root_name in ("documents", "failed"):
        used_ids.extend(
            path.name for path in (output / root_name).glob("*/*")
            if path.is_dir() and re.fullmatch(r"[a-z][a-z0-9_]*_\d{6}", path.name)
        )
    next_id = max((int(name.rsplit("_", 1)[1]) for name in used_ids), default=0) + 1
    if a.seed is None:
        # Continue after every seed already used in this output, so runs never repeat content or design draws.
        used_seeds = [json.loads(path.read_text(encoding="utf-8")).get("seed", 0)
                      for root_name in ("documents", "failed")
                      for path in (output / root_name).glob(f"{a.doc_type}/*/spec.json")]
        a.seed = max(used_seeds, default=0) + 1
        log(f"seeds start at {a.seed} (after the seeds already in {output}); pass --seed to reproduce a run")
    counts = {lang: row["documents"] for lang, row in stats(output).get(a.doc_type, {}).items()}
    failures = 0
    records: list[DocumentRunRecord] = []
    batch_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(a.jobs)

    batches = []
    for batch_start in range(0, a.n, a.batch):
        batch_plans = []
        batch_end = min(a.n, batch_start + a.batch)
        batch_id = f"{run_id[:8]}_{batch_start // a.batch + 1:04}"
        for index in range(batch_start, batch_end):
            first_id = next_id
            next_id += a.designs
            ids = [f"{a.doc_type}_{first_id + offset:06}" for offset in range(a.designs)]
            seed = a.seed + index
            rng = Random(seed)
            base_config = config_catalog[a.doc_type]
            if a.command == "redesign":
                lang = a.lang
            else:
                lang = (raw.get("variables", {}).get("lang") if raw and raw.get("variables") else None)
                lang = lang or (choose_language(counts, seed, a.lang) if not a.fixture else "vi")
            variables = raw.get("variables") if raw else None
            variables = variables or {
                key: (choices[0] if a.fixture else rng.choice(choices))
                for key, choices in base_config.for_lang(lang).variables.items()
            }
            counts[lang] = counts.get(lang, 0) + 1
            variables = {**variables, "lang": lang}
            config = base_config.for_lang(lang)
            config.variables = {**config.variables, "lang": ["vi", "en"]}
            started = datetime.now(timezone.utc)
            trace = Trace(doc_id=ids[0], factory_version="0.1.0", started=started)
            trace.events.append(TraceEvent(
                time=started, stage="spec", kind="check",
                detail={"seed": seed, "lang": lang, "variables": variables,
                        "content_id": raw.get("content_id", ids[0]) if raw else ids[0],
                        "batch_id": batch_id},
            ))
            batch_plans.append({
                "ids": ids,
                "seed": seed,
                "rng": rng,
                "lang": lang,
                "variables": variables,
                "config": config,
                "trace": trace,
                "started_clock": time.monotonic(),
                "content_id": raw.get("content_id", ids[0]) if raw else ids[0],
            })
        batches.append((batch_id, batch_plans))
    log(f"run {run_id[:8]}: {a.n} document(s) of {a.doc_type}, batch {a.batch}, jobs {a.jobs}, "
        f"design {a.design}, output {output}")
    for _, plans in batches:
        for plan in plans:
            log(f"planned: lang {plan['lang']}, seed {plan['seed']}, "
                f"{plan['variables'].get('industry', '')} / {plan['variables'].get('company_size', '')}", plan["ids"][0])

    async def process_batch(batch_id: str, plans: list[dict]):
        nonlocal failures
        async with semaphore:
            conversation = {"summaries": []}
            ready = []
            for plan in plans:
                context = Context(plan["rng"], router, browser, taxonomy, plan["trace"])
                agent = DocumentAgent(
                    plan["config"], plan["variables"], context, plan["lang"],
                    design_seed(plan["seed"], 0), design_entries(a.doc_type, output),
                    doc_type=a.doc_type, conversation=conversation,
                )
                try:
                    if raw is not None:
                        content = validate_content(
                            plan["config"], raw["values"], lang=plan["lang"], variables=plan["variables"],
                        )
                        agent._add_summary(content)
                    else:
                        log(f"elements: start (pool entry {agent.pool.name if agent.pool else '-'})", plan["ids"][0])
                        content = await agent.elements()
                        log("elements: accepted", plan["ids"][0])
                    ready.append({**plan, "agent": agent, "content": content, "element_error": None})
                except Exception as exc:
                    log(f"FAILED at elements: {short(exc)}", plan["ids"][0])
                    ready.append({**plan, "agent": agent, "content": None, "element_error": exc})

            design_items = []
            for plan in ready:
                if plan["element_error"] is not None:
                    for design_index, doc_id in enumerate(plan["ids"]):
                        spec = DocSpec(
                            doc_id=doc_id, doc_type=a.doc_type, seed=plan["seed"],
                            lang=plan["lang"], variables=plan["variables"], design=a.design,
                            content_id=plan["content_id"], design_index=design_index,
                            design_seed=design_seed(plan["seed"], design_index), batch_id=batch_id,
                        )
                        trace = _clone_trace(plan["trace"], doc_id)
                        _save_failed(output, spec, trace, "elements", plan["element_error"],
                                     plan["agent"].latest_element_reply, None, None)
                        records.append(_record(
                            trace, doc_id, plan["lang"], "failed",
                            time.monotonic() - plan["started_clock"], "elements",
                        ))
                        failures += 1
                    continue

                for design_index, doc_id in enumerate(plan["ids"]):
                    spec = DocSpec(
                        doc_id=doc_id, doc_type=a.doc_type, seed=plan["seed"],
                        lang=plan["lang"], variables=plan["variables"], design=a.design,
                        content_id=plan["content_id"], design_index=design_index,
                        design_seed=design_seed(plan["seed"], design_index), batch_id=batch_id,
                    )
                    trace = _clone_trace(plan["trace"], doc_id)
                    context = Context(plan["rng"], router, browser, taxonomy, trace)
                    agent = DocumentAgent(
                        plan["config"], plan["variables"], context, plan["lang"],
                        design_seed(plan["seed"], 0), design_entries(a.doc_type, output),
                        doc_type=a.doc_type, conversation=conversation,
                    )
                    target = output / ".tmp" / a.doc_type / doc_id
                    if target.exists():
                        raise FileExistsError(f"Stale staging folder: {target}")
                    target.mkdir(parents=True)
                    design_items.append({
                        "spec": spec, "content": plan["content"], "trace": trace,
                        "agent": agent, "target": target, "plan": plan,
                        "stage": "design", "result": None, "design_reply": None,
                    })

            if not design_items:
                return

            # The coding agent designs documents concurrently; the legacy batch call shares one turn.
            async with (batch_lock if a.design == "legacy" else contextlib.nullcontext()):
                replies = {}
                batch_error = None
                if a.design == "agent":
                    ledger = design_entries(a.doc_type, output)
                    for item in design_items:
                        item["agent"].ledger_entries = ledger
                        item["agent"].ledger = [ledger_summary(row) for row in ledger]
                if a.design == "legacy":
                    ledger = design_entries(a.doc_type, output)
                    for item in design_items:
                        item["agent"].ledger_entries = ledger
                        item["agent"].ledger = [ledger_summary(row) for row in ledger]
                    before = len(design_items[0]["agent"].ctx.trace.events)
                    log(f"design: requesting {len(design_items)} design(s) in one call "
                        f"({', '.join(item['spec'].doc_id for item in design_items)})")
                    try:
                        replies = await design_items[0]["agent"].design_batch([
                            (item["content"], item["spec"], item["target"]) for item in design_items
                        ])
                    except Exception as exc:
                        batch_error = exc
                    _spread_batch_call(design_items, before)

                for ordinal, item in enumerate(design_items, 1):
                    spec = item["spec"]
                    content = item["content"]
                    agent = item["agent"]
                    target = item["target"]
                    source_plan = item["plan"]
                    try:
                        if a.design == "default":
                            result = await _default_design(item, browser, taxonomy)
                        elif a.design == "agent":
                            try:
                                result = await design_with_tools(agent, content, spec, target)
                            finally:
                                item["design_reply"] = agent.latest_design_reply
                        else:
                            reply = replies.get(ordinal)
                            if reply is not None:
                                item["design_reply"] = json.dumps(
                                    {"design_spec": reply.design_spec, "css": reply.css, "pages": reply.pages},
                                    ensure_ascii=False,
                                )
                                agent.latest_design_reply = item["design_reply"]
                                try:
                                    result = await render_design(agent, content, spec, target, reply)
                                except Exception as exc:
                                    result = None
                                    problem = exc
                            elif isinstance(batch_error, JsonRepairFailure):
                                raise batch_error
                            elif batch_error is not None and "exceeds hard cap" in str(batch_error):
                                raise ValueError(str(batch_error))
                            else:
                                result = None
                                problem = batch_error or ValueError("design batch omitted this document")
                                try:
                                    result = await agent.design(content, spec, target)
                                    item["design_reply"] = agent.latest_design_reply
                                except JsonRepairFailure:
                                    raise
                                except Exception as exc:
                                    result = None
                                    problem = exc
                            if result is None:
                                log(f"design: needs repair: {short(problem)}", spec.doc_id)
                                repair_attempts = 0
                                while (repair_attempts < DESIGN_REPAIR_ROUNDS
                                       and agent._call_counts["design_repair"] < DESIGN_REPAIR_ROUNDS):
                                    repair_attempts += 1
                                    images = _contact_images(target, spec.doc_id)
                                    _reset_stage(target)
                                    try:
                                        result = await agent.design(
                                            content, spec, target, images=images, repair=True,
                                            latest_design=agent.latest_design_reply,
                                            problems=str(problem),
                                        )
                                        item["design_reply"] = agent.latest_design_reply
                                        break
                                    except JsonRepairFailure:
                                        raise
                                    except Exception as exc:
                                        problem = exc
                                        log(f"design: repair failed: {short(exc)}", spec.doc_id)
                                        item["design_reply"] = agent.latest_design_reply
                                if result is None:
                                    raise problem
                        result.manifest.provenance.update({
                            "content_id": spec.content_id,
                            "design_index": str(spec.design_index),
                        })
                        source_content = SourceContent(
                            variables=source_plan["variables"], lang=source_plan["lang"],
                            pool_entry=content.pool_entry, values=content.values,
                        )
                        (target / "document.json").write_text(
                            result.manifest.model_dump_json(indent=2) + "\n", encoding="utf-8",
                        )
                        (target / "source_content.json").write_text(
                            source_content.model_dump_json(indent=2) + "\n", encoding="utf-8",
                        )
                        item["trace"].status = "ok"
                        item["trace"].finished = datetime.now(timezone.utc)
                        _write_trace(target / "trace.json", item["trace"])
                        destination = output / "documents" / a.doc_type / spec.doc_id
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(target), str(destination))
                        if a.design in ("agent", "legacy"):
                            saved_spec = DesignSpec.model_validate_json(
                                (destination / "design" / "design_spec.json").read_text(encoding="utf-8")
                            )
                            append_design(a.doc_type, saved_spec, output, spec.doc_id)
                            refreshed = design_entries(a.doc_type, output)
                            for pending in design_items[ordinal:]:
                                pending["agent"].ledger_entries = refreshed
                                pending["agent"].ledger = [ledger_summary(row) for row in refreshed]
                        records.append(_record(
                            item["trace"], spec.doc_id, spec.lang, "ok",
                            time.monotonic() - source_plan["started_clock"],
                        ))
                        record = records[-1]
                        log(f"ACCEPTED: {record.calls} calls, {record.tokens_in:,} in / {record.tokens_out:,} out, "
                            f"{record.seconds:.0f}s -> {destination}", spec.doc_id)
                    except Exception as exc:
                        design_html = None
                        candidate = target / "design" / "design.html"
                        if candidate.is_file():
                            design_html = candidate.read_text(encoding="utf-8")
                        if target.exists():
                            shutil.rmtree(target)
                        _save_failed(
                            output, spec, item["trace"], item["stage"], exc,
                            item["plan"]["agent"].latest_element_reply,
                            item["design_reply"] or agent.latest_design_reply,
                            design_html,
                            SourceContent(variables=source_plan["variables"], lang=source_plan["lang"],
                                          pool_entry=content.pool_entry, values=content.values)
                            if content is not None else None,
                        )
                        records.append(_record(
                            item["trace"], spec.doc_id, spec.lang, "failed",
                            time.monotonic() - source_plan["started_clock"], item["stage"],
                        ))
                        failures += 1
                        log(f"FAILED at {item['stage']}: {short(exc)}", spec.doc_id)

    await asyncio.gather(*(process_batch(batch_id, plans) for batch_id, plans in batches))
    _clean_tmp(output)
    rebuild_index(output)
    gallery(output)
    run = RunRecord(
        run_id=run_id,
        command=f"{a.command} {a.doc_type} --n {a.n} --batch {a.batch} --jobs {a.jobs}",
        started=run_started,
        ended=datetime.now(timezone.utc),
        documents=records,
    )
    run_dir = output / "runs" / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    violations = check_tree(output)
    for violation in violations:
        log(f"output contract: {violation}")
    accepted = sum(record.status == "ok" for record in records)
    log(f"run {run_id[:8]} done: {accepted} accepted, {len(records) - accepted} failed, "
        f"{sum(r.calls for r in records)} calls, {sum(r.tokens_in for r in records):,} in / "
        f"{sum(r.tokens_out for r in records):,} out, ${sum(r.cost_usd for r in records):.4f}, "
        f"{(run.ended - run.started).total_seconds():.0f}s")
    log(f"run record: {run_dir / 'run.json'}")
    log(f"gallery:    {output / 'gallery.html'}")
    return int(bool(failures or violations))


async def execute(args) -> int:
    taxonomy = Taxonomy()
    output = args.output.resolve()
    if args.command == "gallery":
        print(gallery(args.path.resolve()))
        return 0
    if args.command == "index":
        rebuild_index(output)
        print(LanguageStats.model_validate(stats(output)).model_dump_json(indent=2))
        return 0
    if args.command == "lint":
        async with Browser() as browser:
            issues = await lint_document(args.path, browser, taxonomy)
        print("\n".join(map(str, issues)))
        return int(bool(issues))
    if args.command == "preview":
        manifest = json.loads((args.path / "document.json").read_text(encoding="utf-8"))
        image_dir = args.path / "images"
        image_dir.mkdir(exist_ok=True)
        async with Browser() as browser:
            for page in manifest["pages"]:
                image = await browser.render(args.path / page["file"], dpi=200)
                (image_dir / f"page_{page['index']:03}.png").write_bytes(image)
        return 0
    async with Browser() as browser:
        if args.command == "export":
            from factory.runner.export import export
            return await export(output, args.to, args.allow_imbalance)
        if args.command == "verify":
            errors = await verify_output(output, browser, taxonomy)
            print(json.dumps(errors, ensure_ascii=False))
            return int(bool(errors))
        return await _generate(args, output, browser, taxonomy)


def main() -> None:
    parser = argparse.ArgumentParser(prog="factory")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "redesign"):
        command = subcommands.add_parser(name)
        if name == "generate":
            command.add_argument("doc_type")
            command.add_argument("--fixture", type=Path)
            command.add_argument("--n", type=int, default=1)
        else:
            command.add_argument("path", type=Path)
            command.set_defaults(fixture=None, n=1)
        command.add_argument("--design", choices=["agent", "legacy", "default"], default="agent",
                             help="agent: tool-using design agent; legacy: one-shot JSON with repair rounds")
        command.add_argument("--designs", type=int, default=1)
        command.add_argument("--batch", type=int, default=1)
        command.add_argument("--seed", type=int, default=None,
                             help="first seed; default: one past the highest seed already in the output")
        command.add_argument("--jobs", type=int, default=2)
        command.add_argument("--model")
        command.add_argument("--lang", choices=["vi", "en"])
        command.add_argument("--quiet", action="store_true", help="no progress log")
    for name in ("lint", "preview", "gallery"):
        subcommands.add_parser(name).add_argument("path", type=Path)
    for name in ("index", "verify"):
        subcommands.add_parser(name)
    export = subcommands.add_parser("export")
    export.add_argument("--to", type=Path, required=True)
    export.add_argument("--allow-imbalance", action="store_true")
    for command in subcommands.choices.values():
        command.add_argument("--output", type=Path, default=ROOT / "out")
    args = parser.parse_args()
    if args.command in {"generate", "redesign"} and min(args.n, args.designs, args.batch, args.jobs) < 1:
        parser.error("--n, --designs, --batch and --jobs must be positive")
    progress.QUIET = getattr(args, "quiet", False)
    raise SystemExit(asyncio.run(execute(args)))


if __name__ == "__main__":
    main()
