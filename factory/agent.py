"""Per-document content and design agent with bounded, rebuilt history."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import jinja2
import math
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from factory.content.config import TypeConfig, load_config
from factory.content.pool import fill_pool, mixed_case, select_pool
from factory.content.schema import Content, ContentError, cell, check_chart, validate_content
from factory.contract.models import TraceEvent
from factory.design.draws import draws
from factory.design.ledger import summary as ledger_summary
from factory.llm.client import parse_json
from factory.log import log, short
from factory.paths import ROOT
from factory.render.blocks import SIZES
from factory.design.skeleton import skeleton_prompt
from factory.design.params import draw_params, prompt_lines


ELEMENTS_HARD_CAP = 9_000
ELEMENT_REPAIR_HARD_CAP = 9_000
DESIGN_HARD_CAP = 12_000
DESIGN_REPAIR_HARD_CAP = 16_000
DESIGN_REPAIR_ROUNDS = 4
FONT_FILES = {
    "Be Vietnam Pro": "BeVietnamPro-Regular.ttf",
    "Inter": "Inter-VF.ttf",
    "Lora": "Lora-VF.ttf",
    "Merriweather": "Merriweather-VF.ttf",
    "Montserrat": "Montserrat-VF.ttf",
    "Noto Sans": "NotoSans-VF.ttf",
    "Noto Serif": "NotoSerif-VF.ttf",
    "Source Serif 4": "SourceSerif4-VF.ttf",
}


class ContentReply(BaseModel):
    values: dict[str, Any]


class DesignReply(BaseModel):
    """CSS and per-page choices; code builds the page structure (factory/design/skeleton.py)."""
    design_spec: dict[str, Any]
    css: str
    pages: dict[str, Any] = {}
    layout_plan: dict[str, Any] = Field(default_factory=dict)


class BatchDesignReply(BaseModel):
    designs: list[dict[str, Any]]


class JsonRepairFailure(ValueError):
    """A JSON-only repair reply remained invalid."""


class DocumentAgent:
    """Generate one document's content and design using a compact transcript."""

    def __init__(self, config: TypeConfig, variables: dict, ctx, lang: str,
                 design_seed: int, ledger, *, doc_type: str | None = None,
                 conversation: dict | None = None):
        self.config = config
        self.variables = dict(variables)
        self.ctx = ctx
        self.lang = lang
        self.design_seed = design_seed
        self.ledger_entries = list(ledger or [])
        history = self.ledger_entries if config.design.get("mode") == "backbone" else self.ledger_entries[-4:]
        self.ledger = [ledger_summary(entry) for entry in history]
        self.doc_type = doc_type or config.document_type or "document"
        self.fields = {field.id: field for field in config.fields}
        self.shared = load_config()
        self.design_config = yaml.safe_load((ROOT / "configs/design.yaml").read_text(encoding="utf-8"))
        fixed_rules = {
            key: self.design_config[key]
            for key in ("criteria", "randomness", "distinctness", "design_spec", "slot_format")
        }
        self.system = "\n\n".join((
            self.shared.system.strip(),
            self.design_config["system_prompt"].strip(),
            yaml.safe_dump(fixed_rules, allow_unicode=True, sort_keys=False).strip(),
        ))
        self.conversation = conversation if conversation is not None else {"summaries": []}
        self.pool = select_pool(self.doc_type, lang, self.variables, design_seed)
        self.requested_ids = self._requested_fields()
        # The doc type's prompt (configs/doc_types/*.yaml), filled with this document's variables.
        self.brief = jinja2.Template(config.prompt, undefined=jinja2.StrictUndefined).render(**variables).strip()
        self.elements_task = self._elements_prompt()
        self.latest_element_reply: str | None = None
        self.latest_design_reply: str | None = None
        self._call_counts = {"elements": 0, "element_repair": 0, "design": 0, "design_repair": 0}

    def _requested_fields(self) -> list[str]:
        grouped = [field for group in self.config.elements for field in group.get("fields", [])]
        field_ids = grouped or [field.id for field in self.config.fields]
        pool_fields = set()
        if self.pool:
            pool_fields = set(self.pool.config.get("text", [])) | {self.pool.config.get("notes")}
        result = []
        for field_id in field_ids:
            if field_id in pool_fields or field_id == "notes":
                continue
            if field_id in self.fields and self.fields[field_id].kind == "signature":
                continue
            if field_id not in result:
                result.append(field_id)
        return result

    NOTE_SHAPES = {
        "statement": '{"rows":[{"code":"111","note":"","values":[425000000,360000000]}]} '
                     "(values = [current, prior] as plain JSON integers in VND, not strings)",
        "chart": '{"chart_type":"bar|line|donut","labels":["2023","2024"],'
                 '"series":[{"name":"...","values":[12.5,14.0]}],"unit":"..."} '
                 "(numbers, one per label)",
        "note_tables": '[{"index":1,"header":["...","...","..."],"rows":[["...","...","..."]]}] '
                       "(3–5 columns, 4–8 rows, every row as long as the header)",
        "note_charts": '[{"index":2,"chart_type":"bar|line|donut","labels":["..."],'
                       '"series":[{"name":"...","values":[1.0]}],"unit":"...","caption":"..."}] '
                       "(one value per label, non-negative; donut has one series)",
        "kpis": '[{"label":"...","value":0,"unit":"VND","source":"B02.10"}] (4–6 items; source is statement + "." '
                "+ code, e.g. B02.10 revenue, B02.60 profit after tax, B01.270 total assets, B01.400 equity)",
    }

    def _shape(self, kind: str) -> str:
        """Compact JSON shape of a field kind, from configs/content.yaml field_kinds."""
        if kind in self.NOTE_SHAPES:
            return self.NOTE_SHAPES[kind]
        shape = self.shared.field_kinds.get(kind)
        if shape is None or kind == "signature":
            return ""
        return shape if isinstance(shape, str) else json.dumps(shape, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _one_line(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _statement_catalogue(self, requested: list[str]) -> list[str]:
        lines = []
        requested_statements = {self.fields[field].lines for field in requested if field in self.fields}
        for statement_id in sorted(name for name in requested_statements if name):
            catalogue = self.config.statements.get(statement_id, {})
            lines.append(f"{statement_id}:")
            for code, level, label in catalogue.get("lines", []):
                lines.append(f"{code}|{level}|{self._one_line(str(label))}")
        return lines

    def _elements_prompt(self, only: list[str] | None = None) -> str:
        requested = only or self.requested_ids
        lines = [
            f"ELEMENTS task for a {self.doc_type}; target language: {self.lang}.",
            *([self.brief] if self.brief else []),
            "Use the variables below. Return only the requested field IDs in a JSON object with top-level key values.",
            "Extra keys are ignored. Every row uses values: [integer, integer].",
            "Variables: " + json.dumps(self.variables, ensure_ascii=False, separators=(",", ":")),
            "Requested fields:",
        ]
        for field_id in requested:
            field = self.fields.get(field_id)
            if field is None:
                if field_id == "note_tables":
                    lines.append("note_tables | one indexed 3–5 column table per note; 4–8 rectangular rows")
                elif field_id == "note_charts":
                    lines.append("note_charts | one indexed chart per listed note; 3–6 labels, 1–3 series")
                continue
            detail = " | ".join(part for part in (field.kind, field.section, self._one_line(field.guide)) if part)
            lines.append(f"{field.id} | {detail}")
        kinds = []
        for field_id in requested:
            kind = self.fields[field_id].kind if field_id in self.fields else field_id
            if kind not in kinds:
                kinds.append(kind)
        lines.append("JSON shape for each kind (follow exactly; keys are fixed):")
        lines.extend(f"{kind}: {self._shape(kind)}" for kind in kinds if self._shape(kind))
        if {"cover_company", "auditor_firm"} & set(requested):
            lines.append("cover_company and auditor_firm: in every language, the Vietnamese legal name in upper case "
                         "starting with CÔNG TY (e.g. CÔNG TY CỔ PHẦN ..., CÔNG TY TNHH ...).")
        catalogue = self._statement_catalogue(requested)
        if catalogue:
            lines.extend(["Statement catalogue (code|level|label):", *catalogue])
        if self.pool:
            note_id = self.pool.config["notes"]
            notes = self.pool.values[note_id]
            lines.append("Note titles:")
            lines.extend(f"{index}|{self._one_line(note['title'])}" for index, note in enumerate(notes, 1))
            lines.append("Chart-note indexes: " + ",".join(map(str, self.pool.chart_notes)))
            lines.append("For note_tables, return every note index once. For note_charts, return only listed indexes.")
        lines.append('Return {"values": {"field_id": value}}. Do not include prose outside JSON.')
        return "\n".join(lines)

    def history(self, *, phase: str, task: str | None = None, current: dict | None = None,
                repair: str | None = None, latest_design: str | None = None,
                design_task: str | None = None) -> list[dict[str, Any]]:
        """Rebuild a short transcript without previous malformed model replies."""
        messages = [{"role": "system", "content": self.system}]
        summaries = self.conversation.get("summaries", [])
        summary_prefix = ""
        if summaries:
            summary_prefix = "Previously accepted documents:\n" + "\n".join(summaries) + "\n\n"
        if phase == "elements":
            messages.append({"role": "user", "content": summary_prefix + (task or self.elements_task)})
            if repair:
                accepted = ("Already accepted, do not resend: " + ", ".join(current) + "\n") if current else ""
                messages.append({"role": "user", "content": accepted + repair +
                                 "\nReturn only the fields listed above, inside {\"values\": {...}}."})
            return messages

        # The design task's inventory already describes the content; the elements task is not resent.
        if design_task:
            messages.append({"role": "user", "content": design_task})
        if latest_design:
            messages.append({"role": "assistant", "content": latest_design})
        if repair:
            messages.append({"role": "user", "content": repair})
        return messages

    @staticmethod
    def _json_retry(messages, error) -> list[dict[str, Any]]:
        """Re-ask the same task; the broken reply is not resent."""
        detail = " ".join(str(error).split())[:300]
        return list(messages) + [{
            "role": "user",
            "content": f"Your previous reply was not valid JSON ({detail}). "
                       "Reply again with the complete JSON object only.",
        }]

    @staticmethod
    def _estimate_tokens(messages, images=()) -> int:
        text_size = sum(len(str(message.get("content", ""))) for message in messages)
        # A conservative estimate for JSON, Vietnamese text, and one contact sheet.
        return math.ceil(text_size / 3.3) + 1_000 * len(images)

    async def _call(self, messages, *, kind: str, images=()) :
        cap = {
            "elements": ELEMENTS_HARD_CAP,
            "element_repair": ELEMENT_REPAIR_HARD_CAP,
            "design": DESIGN_HARD_CAP,
            "design_repair": DESIGN_REPAIR_HARD_CAP,
        }[kind]
        estimated = self._estimate_tokens(messages, images)
        if estimated > cap:
            raise ValueError(f"{kind} prompt estimate {estimated} exceeds hard cap {cap}")
        repair_number = self._call_counts[kind] + 1
        self._call_counts[kind] += 1
        doc = self.ctx.trace.doc_id
        log(f"→ {kind} call #{repair_number} (~{estimated:,} tokens in" + (", 1 image" if images else "") + ")", doc)
        started = datetime.now(timezone.utc)
        result = await self.ctx.llm.generate(self.doc_type, messages, images=images)
        seconds = (datetime.now(timezone.utc) - started).total_seconds()
        log(f"← {kind}: {result.tokens_in:,} in / {result.tokens_out:,} out, {seconds:.0f}s"
            + (" (cache)" if result.cached else ""), doc)
        self.ctx.trace.events.append(TraceEvent(
            time=datetime.now(timezone.utc), stage="elements" if kind.startswith("element") else "design",
            kind="llm_call", provider=result.provider, model=result.model,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out, tokens_cached=result.tokens_cached,
            tokens_reasoning=result.tokens_reasoning, cost_usd=result.cost_usd,
            detail={"call_kind": kind, "repair_number": repair_number,
                    "estimated_tokens_in": estimated, "cached": result.cached,
                    "tokens_cached": result.tokens_cached, "tokens_reasoning": result.tokens_reasoning},
        ))
        return result

    def _validate_note_tables(self, value) -> dict:
        if not self.pool or not isinstance(value, list):
            raise ValueError("note_tables: expected an indexed list")
        wanted = set(range(1, len(self.pool.values[self.pool.config["notes"]]) + 1))
        indexes = [item.get("index") for item in value if isinstance(item, dict)]
        if len(indexes) != len(value) or set(indexes) != wanted or len(indexes) != len(wanted):
            raise ValueError(f"note_tables: expected indexes {sorted(wanted)}")
        for item in value:
            header, rows = item.get("header"), item.get("rows")
            if not isinstance(header, list) or not 3 <= len(header) <= 5:
                raise ValueError(f"note_tables[{item['index']}]: header needs 3–5 cells")
            if not isinstance(rows, list) or not 4 <= len(rows) <= 8:
                raise ValueError(f"note_tables[{item['index']}]: needs 4–8 rows")
            if any(not isinstance(row, list) or len(row) != len(header) for row in rows):
                raise ValueError(f"note_tables[{item['index']}]: rows must be rectangular")
            item["header"] = [cell(x) for x in header]
            item["rows"] = [[cell(x) for x in row] for row in rows]
        return {"note_tables": value}

    def _validate_note_charts(self, value) -> dict:
        if not self.pool or not isinstance(value, list):
            raise ValueError("note_charts: expected an indexed list")
        indexes = [item.get("index") for item in value if isinstance(item, dict)]
        if len(indexes) != len(value) or set(indexes) != set(self.pool.chart_notes) or len(indexes) != len(set(indexes)):
            raise ValueError(f"note_charts: expected indexes {self.pool.chart_notes}")
        for item in value:
            chart = {key: child for key, child in item.items() if key != "index"}
            check_chart(chart, lambda text: str(text))
            if not isinstance(chart.get("caption"), str) or not chart["caption"].strip():
                raise ValueError(f"note_charts[{item['index']}]: caption is required")
        return {"note_charts": value}

    def _kind(self, field_id: str) -> str:
        field = self.fields.get(field_id)
        return field.kind if field else field_id

    def _kpi_waiting(self, value, accepted: dict) -> bool:
        """True when a KPI cites a statement that is requested but not accepted yet."""
        if not isinstance(value, list):
            return False
        for item in value:
            source = item.get("source") if isinstance(item, dict) else None
            if isinstance(source, str) and "." in source:
                statement = source.split(".", 1)[0] + "_table"
                if statement in self.requested_ids and statement not in accepted:
                    return True
        return False

    def _validate_field(self, field_id: str, value: Any, values: dict) -> Any:
        if field_id == "note_tables":
            return self._validate_note_tables(value)[field_id]
        if field_id == "note_charts":
            return self._validate_note_charts(value)[field_id]
        field = self.fields.get(field_id)
        if field is None:
            raise ValueError(f"{field_id}: field is not configured")
        if field_id in {"cover_company", "auditor_firm"}:
            try:
                mixed_case(str(value))  # validates only; the printed name keeps the agent's upper case
            except ValueError as exc:
                raise ValueError(f"{field_id}: {exc}") from exc
        dependencies = []
        candidate = {field_id: value}
        if field.kind == "kpis":
            for statement in self.config.fields:
                if statement.kind == "statement" and statement.id in values:
                    dependencies.append(statement)
                    candidate[statement.id] = values[statement.id]
        restricted = self.config.model_copy(update={
            "fields": dependencies + [field],
            "document_type": None,
        })
        try:
            normalized = validate_content(restricted, candidate, lang=self.lang, variables=self.variables)
        except ContentError as exc:
            raise ValueError("; ".join(exc.problems)) from exc
        return normalized.values[field_id]

    def _error_fields(self, problems: list[str], candidate_ids: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        notes_id = self.pool.config["notes"] if self.pool else None
        for problem in problems:
            prefix, separator, _ = problem.partition(":")
            if separator and prefix == notes_id:
                prefix = "note_charts" if "chart" in problem and "note_charts" in candidate_ids else "note_tables"
            if separator and prefix in candidate_ids:
                result.setdefault(prefix, []).append(problem)
        return result

    async def elements(self) -> Content:
        current: dict[str, Any] = {}
        invalid: dict[str, Any] = {}
        deferred: dict[str, Any] = {}  # KPIs waiting for their statements
        pending = list(self.requested_ids)
        repair_number = 0
        parser_error = None
        repair_rounds = min(self.shared.repair_rounds, 2)

        while True:
            if parser_error is not None:
                messages = self._json_retry(last_messages, parser_error)
                result = await self._call(messages, kind="element_repair")
                self.latest_element_reply = result.text
                try:
                    response = ContentReply.model_validate(parse_json(result.text, ContentReply))
                except (ValueError, ValidationError) as exc:
                    parser_error = str(exc)
                    log(f"elements: reply is not valid JSON, asking again ({short(parser_error, 100)})",
                        self.ctx.trace.doc_id)
                    repair_number += 1
                    if repair_number > repair_rounds:
                        raise ValueError(f"elements JSON could not be repaired: {parser_error}") from exc
                    continue
                parser_error = None
            else:
                repair_task = None
                if invalid:
                    request_fields = list(invalid)
                    task = self._elements_prompt(request_fields)
                    details = []
                    for field_id in request_fields:
                        kind = self.fields[field_id].kind if field_id in self.fields else field_id
                        details.append(
                            f"{field_id}: current={json.dumps(invalid[field_id], ensure_ascii=False)[:600]}; "
                            f"problem={' | '.join(field_errors[field_id])}; expected shape={self._shape(kind)}"
                        )
                    repair_task = "Repair only these fields. Keep all accepted fields unchanged.\n" + "\n".join(details)
                    messages = self.history(
                        phase="elements", task=task,
                        current={field_id: self._value_summary(current[field_id])
                                 for field_id in current},
                        repair=repair_task,
                    )
                    kind = "element_repair"
                else:
                    request_fields = pending
                    task = self.elements_task
                    messages = self.history(phase="elements", task=task)
                    kind = "elements"
                last_messages = messages
                result = await self._call(messages, kind=kind)
                self.latest_element_reply = result.text
                try:
                    response = ContentReply.model_validate(parse_json(result.text, ContentReply))
                except (ValueError, ValidationError) as exc:
                    parser_error = str(exc)
                    log(f"elements: reply is not valid JSON, asking again ({short(parser_error, 100)})",
                        self.ctx.trace.doc_id)
                    repair_number += 1
                    if repair_number > repair_rounds:
                        raise ValueError(f"elements JSON could not be repaired: {parser_error}") from exc
                    continue

            values = dict(response.values)
            request_fields = list(invalid) if invalid else pending
            for field_id, value in deferred.items():
                values.setdefault(field_id, value)
            errors: dict[str, list[str]] = {}
            next_invalid: dict[str, Any] = {}
            # Statements first, so KPIs are checked against accepted statements.
            request_fields = sorted(request_fields, key=lambda f: self._kind(f) == "kpis")
            for field_id in request_fields:
                if self._kind(field_id) == "kpis" and field_id in values and self._kpi_waiting(values[field_id], current):
                    deferred[field_id] = values[field_id]
                    continue
                deferred.pop(field_id, None)
                if field_id not in values:
                    errors[field_id] = [f"{field_id}: missing from values"]
                    next_invalid[field_id] = current.get(field_id)
                    continue
                try:
                    current[field_id] = self._validate_field(field_id, values[field_id], current)
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    message = str(exc)
                    if not message.startswith(field_id + ":"):
                        message = f"{field_id}: {message}"
                    errors[field_id] = [message]
                    next_invalid[field_id] = values[field_id]

            log(f"elements: {len(request_fields) - len(errors) - len(deferred)}/{len(request_fields)} fields valid"
                + (f", {len(deferred)} KPI field waiting for statements" if deferred else "")
                + (f"; {len(errors)} to repair, e.g. {short(next(iter(errors.values()))[0], 120)}" if errors else ""),
                self.ctx.trace.doc_id)
            self.ctx.trace.events.append(TraceEvent(
                time=datetime.now(timezone.utc), stage="elements", kind="check",
                detail={"valid_fields": sorted(set(request_fields) - set(errors)),
                        "problems": [p for field_problems in errors.values() for p in field_problems]},
            ))
            if not errors and deferred:
                # Every statement is accepted now; a KPI that still fails has a real error.
                for field_id, value in list(deferred.items()):
                    try:
                        current[field_id] = self._validate_field(field_id, value, current)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        message = str(exc)
                        errors[field_id] = [message if message.startswith(field_id + ":") else f"{field_id}: {message}"]
                        next_invalid[field_id] = value
                    del deferred[field_id]
                if errors:
                    log(f"elements: KPI check failed: {short(next(iter(errors.values()))[0], 120)}",
                        self.ctx.trace.doc_id)
            if not errors:
                invalid = {}
                try:
                    merged = fill_pool(self.pool, self.variables, current)
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    errors = self._error_fields([str(exc)], self.requested_ids)
                    if not errors:
                        raise
                    invalid = {field_id: current.get(field_id) for field_id in errors}
                    field_errors = errors
                    if repair_number >= repair_rounds:
                        raise ContentError([problem for rows in errors.values() for problem in rows]) from exc
                    repair_number += 1
                    pending = list(invalid)
                    continue
                try:
                    content = validate_content(self.config, merged, lang=self.lang, variables=self.variables)
                except ContentError as exc:
                    errors = self._error_fields(exc.problems, self.requested_ids)
                    if not errors:
                        raise
                    invalid = {field_id: current.get(field_id) for field_id in errors}
                else:
                    content.pool_entry = self.pool.name if self.pool else None
                    self._add_summary(content)
                    return content
            else:
                invalid = next_invalid

            if repair_number >= repair_rounds:
                problems = [problem for field_problems in errors.values() for problem in field_problems]
                raise ContentError(problems)
            # The repair prompt in the next iteration includes only the failed fields.
            field_errors = errors
            repair_number += 1
            pending = list(invalid)

    def _add_summary(self, content: Content) -> None:
        if not hasattr(self.conversation, "setdefault"):
            return
        values = content.values
        inventory = []
        for field_id, value in values.items():
            if isinstance(value, dict) and isinstance(value.get("rows"), list):
                inventory.append(f"{field_id}={len(value['rows'])} rows")
            elif isinstance(value, list):
                inventory.append(f"{field_id}={len(value)} items")
        summary = {
            "document": self.doc_type,
            "company": str(values.get("cover_company", ""))[:90],
            "size": str(self.variables.get("company_size", "")),
            "industry": str(self.variables.get("industry", ""))[:60],
            "inventory": ", ".join(inventory[:8]),
        }
        self.conversation.setdefault("summaries", []).append(
            "Accepted document summary: " + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        )

    @staticmethod
    def _value_summary(value: Any) -> str:
        if isinstance(value, dict):
            rows = value.get("rows")
            header = value.get("header")
            if isinstance(rows, list):
                return f"table {len(rows)} rows × {len(header or [])} cols"
            return "object"
        if isinstance(value, list):
            return f"list {len(value)} items"
        if isinstance(value, str):
            return f"text {len(value.split())} words"
        return type(value).__name__

    async def design(self, content: Content, spec, target, *, images=(), repair=False,
                     latest_design=None, problems=None):
        """Design turn; rendered and checked by the design module."""
        from factory.design.agent import render_design

        design_task = self._design_prompt(content, spec)
        if repair:
            from factory.design.checks import summarize_problems

            task = ("Repair only this design. Preserve content and return the full corrected design JSON.\n"
                    + summarize_problems([problems]))
            messages = self.history(phase="design", design_task=design_task,
                                    current=content.values, latest_design=latest_design,
                                    repair=task)
            call_kind = "design_repair"
        else:
            messages = self.history(phase="design", design_task=design_task, current=content.values)
            call_kind = "design"
        result = await self._call(messages, kind=call_kind, images=images)
        self.latest_design_reply = result.text
        try:
            parsed = DesignReply.model_validate(parse_json(result.text, DesignReply))
        except (ValueError, ValidationError) as exc:
            if self._call_counts["design_repair"] >= DESIGN_REPAIR_ROUNDS:
                raise JsonRepairFailure(f"design JSON repair limit reached: {exc}") from exc
            repair_messages = self._json_retry(messages, exc)
            repaired = await self._call(repair_messages, kind="design_repair")
            self.latest_design_reply = repaired.text
            try:
                parsed = DesignReply.model_validate(parse_json(repaired.text, DesignReply))
            except (ValueError, ValidationError) as repair_error:
                raise JsonRepairFailure(f"design JSON could not be repaired: {repair_error}") from repair_error
        return await render_design(self, content, spec, target, parsed)

    async def design_batch(self, items):
        """Request every design in a batch in one model turn."""
        documents = []
        for ordinal, (content, spec, _) in enumerate(items, 1):
            documents.append({"doc": ordinal, "doc_id": spec.doc_id,
                              "task": self._design_prompt(content, spec, batch=True)})
        tasks = "\n".join(
            f"DOCUMENT {row['doc']} ({row['doc_id']}):\n{row['task']}" for row in documents
        )
        request = (
            "Design every listed document in this batch. Make designs distinct from each other and "
            "the ledger. Return exactly {\"designs\":[{\"doc\":1,\"design_spec\":{...},\"css\":\"...\",\"pages\":{...}}]}.\n"
            + tasks
        )
        summaries = self.conversation.get("summaries", [])
        prefix = "Previously accepted documents:\n" + "\n".join(summaries) + "\n\n" if summaries else ""
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": prefix + request},
        ]
        result = await self._call(messages, kind="design")
        self.latest_design_reply = result.text
        try:
            batch = BatchDesignReply.model_validate(parse_json(result.text, BatchDesignReply))
        except (ValueError, ValidationError) as exc:
            if self._call_counts["design_repair"] >= DESIGN_REPAIR_ROUNDS:
                raise JsonRepairFailure(f"design batch JSON repair limit reached: {exc}") from exc
            repair_messages = self._json_retry(messages, exc)
            repaired = await self._call(repair_messages, kind="design_repair")
            self.latest_design_reply = repaired.text
            try:
                batch = BatchDesignReply.model_validate(parse_json(repaired.text, BatchDesignReply))
            except (ValueError, ValidationError) as repair_error:
                raise JsonRepairFailure(
                    f"design batch JSON could not be repaired: {repair_error}"
                ) from repair_error
        replies = {}
        for row in batch.designs:
            ordinal = row.get("doc")
            if type(ordinal) is not int or ordinal in replies:
                raise ValueError("design batch must return each integer doc index once")
            replies[ordinal] = DesignReply.model_validate(row)
        expected = set(range(1, len(items) + 1))
        if set(replies) != expected:
            raise ValueError(f"design batch indexes must be {sorted(expected)}")
        return replies

    def design_params(self, seed: int) -> dict:
        """Code-drawn design parameters, distinct from the recent ledger; fixed once per document."""
        from factory.design.checks import _spec_from_ledger
        from factory.design.params import draw_distinct_params

        cache = self.__dict__.setdefault("_design_params", {})
        if seed not in cache:
            recent = [_spec_from_ledger(row).get("params") or {} for row in self.ledger_entries[-4:]]
            cache[seed] = draw_distinct_params(seed, recent)
        return cache[seed]

    def _design_prompt(self, content: Content, spec, *, batch: bool = False) -> str:
        # Kept compact: one line per slot, with simple size facts only.
        inventory = []
        for field in content.config.fields:
            value = content.values.get(field.id)
            if isinstance(value, dict):
                rows = value.get("rows", [])
                columns = value.get("header", [])
                size = f"{len(rows)} rows × {len(columns)} cols" if rows else f"{len(columns)} cols"
            elif isinstance(value, list):
                size = f"{len(value)} items"
            elif value is None:
                size = "optional/empty"
            else:
                size = f"{len(str(value).split())} words"
            inventory.append(f"{field.id} | {field.kind} | {field.section or '-'} | {size}")
        response_rule = (
            "Include this document's design_spec and html in its numbered batch entry; code adds seed/draws."
            if batch else
            'Return {"design_spec":{...},"css":"...","pages":{"<role or all>":{"order":["<data-k>",...],'
            '"groups":[{"class":"...","items":["<data-k>",...]}],"decor":["<class>",...],"class":"..."}}}. '
            'Do not include seed/draws/orientation; code adds them.'
        )
        return "\n".join([
            f"DESIGN task for {self.doc_type}, document {spec.doc_id}.",
            f"Seed: {spec.design_seed}. Draws (rounded to 4 decimals): " +
            json.dumps({key: [round(draw, 4) for draw in value]
                        for key, value in draws(spec.design_seed).items()},
                       separators=(",", ":")),
            "Ledger: " + "\n".join(self.ledger[-4:]),
            "Local fonts (family=file): " + ", ".join(
                f"{family}={filename}" for family, filename in FONT_FILES.items()
            ),
            *prompt_lines(self.design_params(spec.design_seed)),
            'design_spec.details values are objects, e.g. {"rule":"..."}.',
            "Pages (fixed structure, built by code; data-k names the <main> blocks you may reorder):\n"
            + skeleton_prompt(self.doc_type, content.lang or self.lang,
                              content.config.design.get("fixed_labels", {})),
            "Inventory (slot | kind | section | size):\n" + "\n".join(inventory),
            response_rule,
        ])
