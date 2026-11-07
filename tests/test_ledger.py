from factory.contract.models import DesignSpec
from factory.design.ledger import append, entries


def test_append_accepts_validated_design_spec(tmp_path):
    spec = DesignSpec(
        mode="backbone",
        content_id="paper_01",
        brief={"concept": "archival proceedings"},
        layout_plan={"roles": {"body": {"regions": []}}},
    )

    append("academic_paper", spec, tmp_path, "academic_paper_000001")

    rows = entries("academic_paper", tmp_path, limit=None)
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "academic_paper_000001"
    assert rows[0]["design_spec"]["content_id"] == "paper_01"
