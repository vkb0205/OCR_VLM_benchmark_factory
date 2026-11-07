import pytest

from factory.content.config import load_config
from factory.contract.extract import parse_html
from factory.contract.taxonomy import Taxonomy
from factory.design.backbone import BackboneError, build, default_plan, derive_ro_level, validate_plan
from factory.render.blocks import SIZES
from factory.render.fill import validate_template


@pytest.fixture
def paper_config():
    return load_config().documents["academic_paper"].for_lang("vi")


def test_backbone_builds_every_slot_and_structural_attribute(paper_config):
    plan = default_plan(paper_config)
    source = build(plan, "vi", paper_config.design["fixed_labels"], paper_config)
    root, sections = validate_template(source, paper_config, Taxonomy())
    slots = [node.attrs["data-slot"] for node in root.walk() if "data-slot" in node.attrs]
    assert sorted(slots) == sorted(field.id for field in paper_config.fields)
    assert len(sections) == 4
    for section in sections:
        regions = [node for node in section.walk() if "data-region" in node.attrs]
        assert [int(node.attrs["data-chain"]) for node in regions] == [1]
        assert all(node.attrs.get("data-flow") for node in regions)
        assert section.attrs["data-ro-level"] == "L0"
        assert section.attrs["data-size"] in SIZES


def test_plan_rejects_narrow_measure_and_non_fitting_float(paper_config):
    narrow = default_plan(paper_config)
    narrow["roles"]["body"]["regions"][0]["box"]["w"] = "40mm"
    with pytest.raises(BackboneError, match="line measure"):
        validate_plan(narrow, paper_config)

    float_plan = default_plan(paper_config)
    float_plan["roles"]["body"]["float_defaults"]["span"] = 2
    with pytest.raises(BackboneError, match="float span"):
        validate_plan(float_plan, paper_config)


def test_plan_requires_every_field_once_and_all_render_sizes(paper_config):
    plan = default_plan(paper_config)
    plan["roles"]["references"]["flow"]["slots"] = []
    with pytest.raises(BackboneError, match="flow slots"):
        validate_plan(plan, paper_config)
    backbone = __import__("factory.design.backbone", fromlist=["load_backbone"]).load_backbone()
    assert set(backbone["allowed_sizes"]) == set(SIZES)


@pytest.mark.parametrize(
    ("boxes", "spans", "expected"),
    [
        ([(0, 0, 1, 1)], [1], "L0"),
        ([(0, 0, 0.48, 1), (0.52, 0, 0.48, 1)], [1, 1], "L1"),
        ([(0, 0, 0.48, 1), (0.52, 0, 0.48, 1)], [2, 1], "L2"),
        ([(0, 0, 0.32, 1), (0.34, 0, 0.32, 1), (0.68, 0, 0.32, 1)], [1, 1, 1], "L3"),
        ([(0, 0, 1, 0.45), (0, 0.5, 1, 0.5)], [1, 1], "L4"),
    ],
)
def test_reading_order_level_is_derived_from_measured_boxes(boxes, spans, expected):
    assert derive_ro_level(boxes, spans) == expected
