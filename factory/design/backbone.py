"""Code-owned academic paper structure and layout-plan validation."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

import yaml

from factory.contract.extract import Element
from factory.paths import ROOT
from factory.render.blocks import SIZES
from factory.render.fill import serialize


class BackboneError(ValueError):
    """A layout plan cannot satisfy the academic-paper backbone."""


REGION_BASE_CSS = (
    "section.page main{position:absolute!important;overflow:hidden!important}"
    "section.page [data-region]{position:absolute!important;overflow:hidden!important;"
    "box-sizing:border-box!important;column-count:auto!important;columns:auto!important}"
    "section.page [data-region]>:last-child{margin-bottom:0!important}"
    "section.page [data-region] [data-slot]{position:static!important;inset:auto!important;"
    "width:auto!important;height:auto!important;max-height:none!important;transform:none!important}"
)


def load_backbone(path: Path | None = None) -> dict:
    """Load the narrow structural contract for the requested document type."""
    source = path or ROOT / "configs" / "backbones" / "academic_paper.yaml"
    data = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("doc_type") != "academic_paper":
        raise BackboneError("invalid academic-paper backbone config")
    if set(data.get("allowed_sizes", [])) != set(SIZES):
        raise BackboneError("backbone allowed_sizes must match render.blocks.SIZES")
    return data


def _number(value, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise BackboneError(f"{name} must be a finite number") from None
    if not math.isfinite(result):
        raise BackboneError(f"{name} must be a finite number")
    return result


def _length(value, name: str) -> tuple[float, str]:
    """Return a positive CSS length as (value, mm|%). Numeric values mean mm."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount, unit = _number(value, name), "mm"
    elif isinstance(value, str):
        match = re.fullmatch(r"\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|%)\s*", value)
        if not match:
            raise BackboneError(f"{name} must use millimetres or percent")
        amount, unit = _number(match.group(1), name), match.group(2)
    else:
        raise BackboneError(f"{name} must use millimetres or percent")
    return amount, unit


def _box_mm(box: dict, main_width: float, main_height: float, name: str) -> tuple[float, float, float, float]:
    if not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}:
        raise BackboneError(f"{name} box requires exactly x, y, w, h")
    values = []
    for key in ("x", "y", "w", "h"):
        value, unit = _length(box[key], f"{name}.{key}")
        if key in {"w", "h"} and value <= 0:
            raise BackboneError(f"{name}.{key} must be positive")
        if key in {"x", "y"} and value < 0:
            raise BackboneError(f"{name}.{key} cannot be negative")
        base = main_width if key in {"x", "w"} else main_height
        values.append(value * base / 100 if unit == "%" else value)
    x, y, width, height = values
    if x + width > main_width + 0.01 or y + height > main_height + 0.01:
        raise BackboneError(f"{name} box must stay inside <main>")
    if height < 35:
        raise BackboneError(f"{name} region is shorter than 35 mm")
    return x, y, width, height


def _region_geometry(page: dict, backbone: dict, name: str) -> list[tuple[int, str, tuple[float, float, float, float]]]:
    size = page.get("size")
    if size not in backbone["allowed_sizes"] or size not in SIZES:
        raise BackboneError(f"{name}: size must be one of {', '.join(SIZES)}")
    page_width, page_height = SIZES[size]
    frame = backbone["frame"]
    margin = float(frame["margin_mm"])
    main_width = page_width - 2 * margin
    main_height = page_height - 2 * margin - float(frame["header_height_mm"]) - float(frame["footer_clearance_mm"])
    regions = page.get("regions")
    if not isinstance(regions, list) or not regions:
        raise BackboneError(f"{name}: at least one region is required")
    if len(regions) > 5:
        raise BackboneError(f"{name}: no more than five regions are allowed")
    found, geometry = set(), []
    for region in regions:
        if not isinstance(region, dict):
            raise BackboneError(f"{name}: every region must be an object")
        chain = region.get("chain")
        region_name = region.get("name")
        if type(chain) is not int or chain < 1 or not isinstance(region_name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", region_name):
            raise BackboneError(f"{name}: each region needs a positive chain and a simple name")
        if chain in found:
            raise BackboneError(f"{name}: region chains must be unique")
        found.add(chain)
        box = _box_mm(region.get("box"), main_width, main_height, f"{name}.{region_name}")
        geometry.append((chain, region_name, box))
    if [row[0] for row in geometry] != sorted(found):
        raise BackboneError(f"{name}: regions must appear in ascending chain order")
    if geometry[0][1] != "body":
        raise BackboneError(f"{name}: the first region must be named body")
    for index, (_, a_name, a) in enumerate(geometry):
        for _, b_name, b in geometry[index + 1:]:
            overlap_x = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            overlap_y = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if overlap_x > 0.25 and overlap_y > 0.25:
                raise BackboneError(f"{name}: regions {a_name} and {b_name} overlap")
    return geometry


def _plain_columns(geometry: list[tuple[int, str, tuple[float, float, float, float]]]) -> bool:
    if len(geometry) <= 1:
        return True
    boxes = [row[2] for row in geometry]
    top, height = boxes[0][1], boxes[0][3]
    return all(abs(box[1] - top) <= 0.5 and abs(box[3] - height) <= 0.5 for box in boxes)


def _role_level(page: dict, geometry) -> str:
    count = len(geometry)
    if count == 1:
        return "L0"
    if count == 2:
        if not _plain_columns(geometry):
            return "L4"
        return "L2" if int((page.get("float_defaults") or {}).get("span", 1)) > 1 else "L1"
    if count >= 3:
        return "L3" if _plain_columns(geometry) else "L4"
    return "L4"


def geometry_signature(boxes: list[tuple[float, float, float, float]]) -> tuple[tuple[float, ...], ...]:
    """Normalised measured boxes; page size and pixel density do not affect the arrangement."""
    return tuple(tuple(round(value, 4) for value in box) for box in boxes)


def derive_ro_level(boxes: list[tuple[float, float, float, float]], spans=()) -> str:
    """Classify measured regions using the v3 reading-order levels."""
    if len(boxes) <= 1:
        return "L0"
    if len(boxes) == 2:
        first, second = boxes
        side_by_side = abs(first[1] - second[1]) <= 0.01 and abs(first[3] - second[3]) <= 0.01
        if not side_by_side:
            return "L4"
        return "L2" if any(int(span or 1) > 1 for span in spans) else "L1"
    same_row = all(abs(box[1] - boxes[0][1]) <= 0.01 and abs(box[3] - boxes[0][3]) <= 0.01
                   for box in boxes)
    return "L3" if same_row else "L4"


def _float_defaults(page: dict, region_count: int, backbone: dict, name: str) -> dict:
    value = page.get("float_defaults") or {}
    span = value.get("span", 1)
    policy = value.get("policy", "here")
    if type(span) is not int or span not in backbone["limits"]["float_spans"] or span > region_count:
        raise BackboneError(f"{name}: float span must fit within the declared regions")
    if policy not in backbone["limits"]["float_policies"]:
        raise BackboneError(f"{name}: unknown float policy {policy!r}")
    return {"span": span, "policy": policy}


def validate_plan(plan: dict, config, backbone: dict | None = None) -> dict:
    """Validate slots, region chains, measures, floats and optional landscape table geometry."""
    backbone = backbone or load_backbone()
    if not isinstance(plan, dict) or not isinstance(plan.get("roles"), dict):
        raise BackboneError("layout_plan must contain a roles object")
    role_configs = backbone["page_roles"]
    if set(plan["roles"]) != set(role_configs):
        raise BackboneError("layout_plan roles must be title_page, body, references, appendix")
    all_fields = {field.id: field for field in config.fields}
    placement_counts = {slot: 0 for slot in all_fields}
    normalized = deepcopy(plan)
    role_geometry, role_levels = {}, {}
    for role, role_config in role_configs.items():
        page = normalized["roles"][role]
        if not isinstance(page, dict):
            raise BackboneError(f"{role}: page layout must be an object")
        geometry = _region_geometry(page, backbone, role)
        chains = {row[0] for row in geometry}
        role_geometry[role] = geometry
        role_levels[role] = _role_level(page, geometry)
        flow = page.get("flow")
        expected_flow_slots = [slot for slot in role_config["slots"] if slot != role_config.get("header_slot")]
        if not isinstance(flow, dict) or not isinstance(flow.get("slots"), list) or not isinstance(flow.get("chains"), list):
            raise BackboneError(f"{role}: flow requires slots and chains lists")
        if flow["slots"] != expected_flow_slots:
            raise BackboneError(f"{role}: flow slots must be {expected_flow_slots}")
        if not flow["chains"] or any(type(chain) is not int or chain not in chains for chain in flow["chains"]):
            raise BackboneError(f"{role}: flow chains must refer to declared regions")
        if flow["chains"] != sorted(set(flow["chains"])):
            raise BackboneError(f"{role}: flow chains must be unique and ascending")
        if flow["chains"] != sorted(chains):
            raise BackboneError(f"{role}: the role flow must traverse every declared region in chain order")
        for slot in role_config["slots"]:
            if slot not in all_fields:
                raise BackboneError(f"backbone slot {slot!r} is absent from the document config")
            placement_counts[slot] += 1
        for chain, region_name, box in geometry:
            if chain not in flow["chains"]:
                continue
            body_font_pt = _number(page.get("body_font_size_pt", 10), f"{role}.body_font_size_pt")
            if body_font_pt < 8:
                raise BackboneError(f"{role}: body font size must be at least 8 pt")
            chars = (box[2] * 72 / 25.4) / (body_font_pt * float(backbone["limits"]["average_glyph_width_em"]))
            if chars + 1e-6 < float(backbone["limits"]["min_line_characters"]):
                raise BackboneError(f"{role}.{region_name}: line measure is {chars:.1f} characters; minimum is 35")
        _float_defaults(page, len(geometry), backbone, role)
    expected_fields = set(all_fields)
    if set(placement_counts) != expected_fields or any(count != 1 for count in placement_counts.values()):
        bad = [f"{slot}={count}" for slot, count in placement_counts.items() if count != 1]
        raise BackboneError("every config field must be placed exactly once: " + ", ".join(bad))
    for slot, field in all_fields.items():
        owner = next((role for role, rc in role_configs.items() if slot in rc["slots"]), None)
        if owner is None or (field.optional and slot not in role_configs[owner].get("optional_slots", [])):
            raise BackboneError(f"{slot}: optionality differs from the backbone")
        if not field.optional and slot in role_configs[owner].get("optional_slots", []):
            raise BackboneError(f"{slot}: required field is marked optional in the backbone")
    wide = normalized.get("wide_table_page")
    if wide is not None:
        wide_geometry = _region_geometry(wide, backbone, "wide_table_page")
        if len(wide_geometry) != 1:
            raise BackboneError("wide_table_page must define exactly one region")
        threshold = wide.get("min_columns", 7)
        if type(threshold) is not int or threshold < 2:
            raise BackboneError("wide_table_page.min_columns must be an integer >= 2")
        normalized["wide_table_page"] = {**wide, "_geometry": wide_geometry}
    normalized["_geometry"] = role_geometry
    normalized["_levels"] = role_levels
    arrangements = {
        tuple((round(box[0], 1), round(box[1], 1), round(box[2], 1), round(box[3], 1)) for _, _, box in geometry)
        for geometry in role_geometry.values()
    }
    document_level = "L4" if len(arrangements) > 1 or "L4" in role_levels.values() else max(role_levels.values(), key=lambda x: int(x[1:]))
    if wide is not None:
        # A landscape table page has a distinct region arrangement from the portrait body.
        wide_size = wide["size"]
        if wide_size not in SIZES:
            raise BackboneError("wide_table_page size must be one of " + ", ".join(SIZES))
        if wide_size != normalized["roles"]["body"]["size"]:
            document_level = "L4" if len(role_geometry["body"]) != 1 else document_level
    normalized["_document_level"] = document_level
    return normalized


def _css_length(value) -> str:
    amount, unit = _length(value, "region dimension")
    return f"{amount:g}{unit}"


def _region_style(box: dict) -> str:
    return ";".join((f"left:{_css_length(box['x'])}", f"top:{_css_length(box['y'])}",
                     f"width:{_css_length(box['w'])}", f"height:{_css_length(box['h'])}"))


def _build_region(region: dict, role: str, flow: dict, float_defaults: dict) -> Element:
    chain = region["chain"]
    name = region["name"]
    attrs = {
        "data-region": name,
        "data-chain": str(chain),
        "data-flow": f"{role}_{chain}",
        "data-flow-group": role,
        "data-flow-chain": str(chain),
        "data-float-span": str(float_defaults["span"]),
        "data-float-policy": float_defaults["policy"],
        "style": _region_style(region["box"]),
    }
    return Element("div", attrs)


def default_plan(config, *, variant: str = "single") -> dict:
    """A conservative one-region plan, primarily for offline fixture generation."""
    layouts = {}
    for role, role_config in load_backbone()["page_roles"].items():
        slots = [slot for slot in role_config["slots"] if slot != role_config.get("header_slot")]
        layouts[role] = {
            "size": "a4",
            "body_font_size_pt": 10,
            "regions": [{"name": "body", "chain": 1, "box": {"x": "0%", "y": "0%", "w": "100%", "h": "100%"}}],
            "flow": {"slots": slots, "chains": [1]},
            "float_defaults": {"span": 1, "policy": "here"},
        }
    return {"roles": layouts}


def _append_frame(section: Element, role: str, role_config: dict, fixed_labels: dict, page: dict,
                  regions: list[dict], geometry, level: str, wide_plan: dict | None) -> None:
    labels = list(fixed_labels.get(role, []))
    header = Element("header", {"data-continued": ""})
    header_slot = role_config.get("header_slot")
    if header_slot:
        header.attrs["data-slot"] = header_slot
    elif len(labels) > 1 and role_config.get("header_label"):
        header.attrs["data-label"] = role_config["header_label"]
        header.children = [str(labels[0])]
    footer = Element("footer", {"aria-hidden": "true"})
    number_text = labels[-1] if labels else "{n} / {total}"
    page_number = Element("span", {"class": "page-number", "data-label": "page_number", "data-continued": ""})
    page_number.children = [str(number_text)]
    main = Element("main")
    flow = page["flow"]
    for region in regions:
        if region["chain"] in flow["chains"]:
            node = _build_region(region, role, flow, _float_defaults(page, len(regions), load_backbone(), role))
            if region["chain"] == flow["chains"][0]:
                for slot in flow["slots"]:
                    slot_attrs = {"data-slot": slot, "data-split": "auto"}
                    if page.get("keep_slot_groups"): slot_attrs["data-keep-slot-group"] = ""
                    node.children.append(Element("div", slot_attrs, parent=node))
            main.children.append(node)
            node.parent = main
    for child in (header, footer, page_number, main):
        child.parent = section
    section.children = [header, footer, page_number, main]
    section.attrs.update({
        "class": "page role-" + role,
        "data-page-role": role,
        "data-size": page["size"],
        "data-ro-level": level,
        "data-layout": ("single_column" if len(regions) == 1 else
                        "multi_column" if _plain_columns(geometry) else "mixed"),
    })
    if wide_plan:
        section.attrs["data-wide-table-plan"] = json.dumps({
            "size": wide_plan["size"], "regions": wide_plan["regions"],
            "min_columns": wide_plan.get("min_columns", 7),
        }, separators=(",", ":"))


def build(plan: dict, lang: str, fixed_labels: dict, config, *, css: str = "", backbone: dict | None = None) -> str:
    """Build HTML from a validated layout plan; structural attributes are always code-generated."""
    from factory.design.skeleton import BASE_CSS

    backbone = backbone or load_backbone()
    plan = validate_plan(plan, config, backbone)
    roles = backbone["page_roles"]
    sections = []
    for role, role_config in roles.items():
        page = plan["roles"][role]
        geometry = plan["_geometry"][role]
        regions = [
            {"name": region["name"], "chain": region["chain"], "box": region["box"]}
            for region in page["regions"]
        ]
        section = Element("section", {"class": "page"})
        _append_frame(section, role, role_config, fixed_labels.get(lang, {}), page, regions,
                      geometry, plan["_document_level"], plan.get("wide_table_page") if role == "body" else None)
        sections.append(serialize(section))
    style = (
        "*{box-sizing:border-box;hyphens:none}html,body{margin:0;padding:0}"
        "body{font-family:'Factory Serif',serif;font-size:10pt;line-height:1.4;color:#171717}"
        "p{margin:0 0 2mm}h1{font-size:16pt}h2{font-size:12pt}"
        "table{width:100%;border-collapse:collapse}td,th{padding:3px;border-bottom:1px solid #777}"
        ".paper-table{table-layout:fixed;font-size:8pt;overflow-wrap:anywhere}"
        ".paper-table th,.paper-table td{padding:1px 2px;overflow-wrap:anywhere;word-break:normal}"
        ".display-equation{max-width:100%}.display-equation .katex{font-size:8pt!important}"
        "figure{margin:2mm 0;max-height:120mm}"
        + REGION_BASE_CSS
        + BASE_CSS
        + "\n"
        + str(css or "")
    )
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f"<style>{style}</style></head><body>" + "\n".join(sections) + "</body></html>")


def apply_wide_table_page(section: Element) -> Element | None:
    """Switch a cloned body page to its code-owned landscape table geometry."""
    raw = section.attrs.get("data-wide-table-plan")
    if not raw:
        return None
    plan = json.loads(raw)
    region_plan = plan["regions"][0]
    from factory.render.fill import replace_inner

    main = next((node for node in section.walk() if node.tag == "main"), None)
    if main is None:
        return None
    old = [node for node in main.children if isinstance(node, Element) and "data-region" in node.attrs]
    if not old:
        return None
    region = old[0]
    for node in old[1:]:
        main.children.remove(node)
        node.parent = None
    region.attrs.update({
        "data-region": region_plan["name"],
        "data-chain": "1",
        "data-flow": "body_1",
        "data-flow-group": "body",
        "data-flow-chain": "1",
        "style": _region_style(region_plan["box"]),
    })
    section.attrs["data-size"] = plan["size"]
    section.attrs["data-layout"] = "single_column"
    return region
