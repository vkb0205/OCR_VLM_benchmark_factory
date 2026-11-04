"""Load, select, and fill immutable prose-pool entries."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import re

import yaml

from factory.contract.taxonomy import ROOT


LEGAL = re.compile(
    r"^(CÔNG\s+TY(?:\s+CỔ\s+PHẦN|\s+TNHH\s+MỘT\s+THÀNH\s+VIÊN|\s+TNHH\s+MTV|\s+TNHH)?)\s*(.*)$", re.IGNORECASE)
LEGAL_CASE = {
    "CÔNG TY CỔ PHẦN": "Công ty Cổ phần",
    "CÔNG TY TNHH": "Công ty TNHH",
    "CÔNG TY TNHH MỘT THÀNH VIÊN": "Công ty TNHH Một thành viên",
    "CÔNG TY TNHH MTV": "Công ty TNHH MTV",
    "CÔNG TY": "Công ty",
}


@dataclass(frozen=True)
class PoolSelection:
    name: str
    values: dict
    config: dict
    chart_notes: list[int]


def pool_config(doc_type: str) -> dict | None:
    path = ROOT / "configs/doc_types" / f"{doc_type}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("pool")


def load_pool(doc_type: str, lang: str = "vi") -> list[tuple[str, dict]]:
    folder = ROOT / "pool" / doc_type / lang
    return [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(folder.glob("*.json"))
    ]


def mixed_case(name: str) -> tuple[str, str]:
    match = LEGAL.match(name.strip())
    if not match:
        raise ValueError("must start with CÔNG TY")
    legal, core = " ".join(match.group(1).upper().split()), match.group(2).strip()
    if not core:
        raise ValueError("company name is missing after CÔNG TY")
    core = " ".join(word.capitalize() for word in core.split())
    return (LEGAL_CASE[legal] + " " + core).strip(), core


def select_pool(doc_type: str, lang: str, variables: dict, seed: int) -> PoolSelection | None:
    config = pool_config(doc_type)
    if not config:
        return None
    pool_lang = lang if lang in {"vi", "en"} else "vi"
    entries = load_pool(doc_type, pool_lang)
    if not entries:
        raise ValueError(f"No prose-pool entries for {doc_type}/{pool_lang}")
    matching = [entry for entry in entries if entry[1].get("variables", {}).get("industry") == variables.get("industry")]
    name, entry = (matching or entries)[seed % len(matching or entries)]
    titles = entry["values"][config["notes"]]
    count = len(titles)
    chart_count = min(count - 1, random.Random(seed + 1).randint(4, 6))
    chart_notes = sorted(random.Random(seed).sample(range(2, count + 1), chart_count))
    return PoolSelection(name, entry["values"], config, chart_notes)


def fill_pool(selection: PoolSelection | None, variables: dict, generated: dict) -> dict:
    """Merge model-authored elements with the selected prose and placeholders."""
    values = dict(generated)
    if selection is None:
        return values

    tables = values.pop("note_tables", None)
    if not isinstance(tables, list):
        raise ValueError("note_tables: must be a list")
    by_index = {}
    for table in tables:
        if not isinstance(table, dict) or type(table.get("index")) is not int:
            raise ValueError("note_tables: each item needs an integer index")
        by_index[table["index"]] = {key: table.get(key) for key in ("header", "rows")}
    wanted = set(range(1, len(selection.values[selection.config["notes"]]) + 1))
    if len(by_index) != len(tables) or set(by_index) != wanted:
        raise ValueError(f"note_tables: indexes must be {sorted(wanted)}")

    charts = values.pop("note_charts", None)
    if not isinstance(charts, list):
        raise ValueError("note_charts: must be a list")
    chart_by_index = {}
    for chart in charts:
        if not isinstance(chart, dict) or type(chart.get("index")) is not int:
            raise ValueError("note_charts: each item needs an integer index")
        chart_by_index[chart["index"]] = {key: value for key, value in chart.items() if key != "index"}
    if len(chart_by_index) != len(charts) or set(chart_by_index) != set(selection.chart_notes):
        raise ValueError(f"note_charts: indexes must be {selection.chart_notes}")

    try:
        company, core = mixed_case(str(values.get("cover_company", "")))
    except ValueError as exc:
        raise ValueError(f"cover_company: {exc}") from exc
    try:
        auditor, auditor_core = mixed_case(str(values.get("auditor_firm", "")))
    except ValueError as exc:
        raise ValueError(f"auditor_firm: {exc}") from exc

    year = int(variables["fiscal_year"])
    tokens = {
        "{company}": company,
        "{core}": core,
        "{auditor}": auditor,
        "{auditor_core}": auditor_core,
        "{year}": str(year),
        "{prev}": str(year - 1),
        "{next}": str(year + 1),
    }

    def fill(text):
        for token, value in tokens.items():
            text = text.replace(token, value)
        return text

    for key in selection.config["text"]:
        item = selection.values[key]
        values[key] = [fill(part) for part in item] if isinstance(item, list) else fill(item)
    values[selection.config["notes"]] = [
        {
            "title": fill(note["title"]),
            "paragraphs": [fill(paragraph) for paragraph in note["paragraphs"]],
            "table": by_index[index],
            "chart": chart_by_index.get(index),
        }
        for index, note in enumerate(selection.values[selection.config["notes"]], 1)
    ]
    return values
