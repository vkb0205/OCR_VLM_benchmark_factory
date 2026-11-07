# GT Review

From the workspace root:

```powershell
./app/run.ps1 ./OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3
```

Open http://127.0.0.1:8765. Requires the factory virtual environment, Python 3.11+, and Node/npm. The launcher installs server dependencies, generates the OpenAPI client, builds Vite, and serves on loopback.

Documents are keyed by subset and document ID. Reviews are atomically written to each subset's `reviews/{doc_id}.json`; document bundles are read only. Concurrent saves carry page versions and return 409 on conflict. Reload after a conflict to fetch the latest state. A changed manifest/content/pagination hash marks the old review stale and excludes it from export.

Keyboard: Tab/Shift+Tab select block, 1–6 record verdict, J/K change page, A/F/R decide page, B/O/I toggle overlays, / focuses search. Shift+drag replaces the selected box. Drag the reading-order list to reorder. Category/attribute corrections save on blur. Text is read only; a text-wrong verdict flags the document.

Approved-only export:

```powershell
./OCR_VLM_benchmark_factory/.venv/Scripts/python.exe -m factory.cli export --output ./OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3 --to ./reviewed-export
./OCR_VLM_benchmark_factory/.venv/Scripts/python.exe -m factory.cli reviews report ./OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3
```

`--include-unreviewed` retains the earlier agent-only selection and skips review corrections. Reviewed exports namespace image names by subset. Export still enforces factory lint; stored factory content problems must be resolved through regeneration outside this app.

Verification scripts and preview evidence live in `checks/`. Review tests clean up their own temporary review files and refuse to overwrite existing reviews. The export comparison replays PDF bytes to hold Chromium's creation timestamps constant while comparing independently measured geometry and screenshots.
