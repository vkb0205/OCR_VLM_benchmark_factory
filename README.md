# Benchmark factory v2

Use `.venv/bin/python -m factory.cli` or the installed `factory` command.

```sh
.venv/bin/python -m pip install -e .
factory generate financial_report --fixture tests/fixtures/financial_report_content.json --design default
factory generate financial_report --n 6 --designs 1
factory lint out/documents/financial_report/financial_report_000001
factory gallery out
factory export --to dataset
.venv/bin/python -m pytest -q tests/test_v2.py tests/test_browser_v2.py
```

API credentials and endpoint/model settings are read from `.env` without being printed. Generated bundles live in `out/documents`; rejected designs and traces live in `out/failed`. Archived v1 code is reference material only.

Implementation and acceptance status are tracked in `todo.md`. Language balance, full browser defect acceptance, and end-to-end acceptance remain incomplete; do not treat this as a finished benchmark release.
