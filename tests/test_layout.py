"""The offline fixture run must stay inside the contracted output tree."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from factory.browser.browser import Browser
from factory.cli import _generate
from factory.contract.taxonomy import Taxonomy
from factory.paths import ROOT
from factory.runner.layout import ALLOWED, _check_bundle, check_tree
from factory.runner.dataset import verify_output


def test_offline_fixture_obeys_output_contract(tmp_path):
    # The fixture must not create repository-root artifacts. Git metadata, local
    # specs, editable installs and a frozen content bank are legitimate inputs;
    # compare against the actual checkout before generation, not a machine snapshot.
    root_before = {path.name for path in ROOT.iterdir() if path.suffix != '.log'}
    output = tmp_path / "out"
    args = SimpleNamespace(
        command="generate",
        doc_type="financial_report",
        fixture=ROOT / "tests/fixtures/financial_report_content.json",
        n=1,
        designs=1,
        batch=1,
        seed=91,
        design="default",
        jobs=1,
        model=None,
        lang="vi",
        output=output,
    )

    async def run():
        async with Browser() as browser:
            status = await _generate(args, output, browser, Taxonomy())
            errors = await verify_output(output, browser, Taxonomy())
            return status, errors

    status, errors = asyncio.run(run())
    assert status == 0
    assert errors == []
    assert check_tree(output) == []
    assert {path.name for path in output.iterdir()} == ALLOWED["out"]
    for bundle in (output / "documents").glob("*/*"):
        assert {path.name for path in bundle.iterdir()} == ALLOWED["accepted"]
    assert {path.name for path in ROOT.iterdir() if path.suffix != '.log'} == root_before


def test_failed_bundle_allows_source_content(tmp_path):
    folder = tmp_path / "failed"
    folder.mkdir()
    for name in ("spec.json", "trace.json", "problems.json", "source_content.json"):
        (folder / name).write_text("{}", encoding="utf-8")
    assert _check_bundle(folder, "failed") == []
