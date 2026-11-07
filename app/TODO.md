# TODO: GT Review app

Spec: `PLAN.md` (section numbers in brackets). Record each check's result under it.

## Phase 1: factory sidecars (factory repo)

- [x] Move the block-capture JavaScript out of `factory/runner/export.py` into one shared function used by export and boxes [2]
- [x] Write `extra/boxes.json` at the end of `generate`: image size, per-block `id`, `cat`, `ro`, `part`, `poly`, `lang`, `parent`, `attrs`, ground truth; ignored regions [2]
- [x] `factory boxes <path>` backfills existing runs [2]
- [x] `factory lint` writes `extra/lint.json` with block id where known [2]
- [x] Document both files in CONTRACT.md (minor version bump) [2]
- [x] **Check:** backfill `out/uniqueness_phase0_attempt3`; boxes drawn on `page_001.png` with a 20-line script land on the text; export output is byte-identical before and after the refactor

  Result: FAILED (2026-11-05). Stopped before phase 2 as instructed. Implementation items above are written, but phase 1 is not verified complete.

  Ran `OCR_VLM_benchmark_factory/.venv/Scripts/python.exe -m factory.cli boxes OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3` from the workspace root. Exit 0; 4 documents, 32 pages, 328 blocks backfilled. Per subset: en_long 10 pages / 93 blocks; en_medium 7 / 71; vi_long 9 / 94; vi_short 6 / 70. No regeneration was run. The bundle writes were the two allowed sidecars only.

  Ran `OCR_VLM_benchmark_factory/.venv/Scripts/python.exe -m factory.cli lint OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3`. Exit 1; all 4 lint sidecars were written, containing 12 findings: en_long 9 C013 errors (`journal`, `references_1` through `references_8`); en_medium 1 C001 decoding error; vi_long and vi_short 1 C001 decoding error each. Representative output: `Extracted content differs from DocIR: journal`; `'charmap' codec can't decode byte 0x81 in position 4524`; `'charmap' codec can't decode byte 0x8f in position 308`. Likely causes: current factory extraction disagrees with the stored English content, and the existing linter uses `Path.read_text()` without explicit UTF-8 on Windows. Lint failure is not evidence of a box measurement failure.

  Ran an inline Pillow overlay script via `OCR_VLM_benchmark_factory/.venv/Scripts/python.exe -` (read each `extra/boxes.json`, compare measured dimensions with the PNG, draw polygons and reading-order labels on each document's `page_001.png`, save previews under `app/checks/`). Exit 1 before any preview was produced: `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 738: character maps to <undefined>`, at `json.loads(p.read_text())`. Cause: the check script itself omitted `encoding="utf-8"`. Visual box alignment is UNVERIFIED. No retry or subsequent phase check was performed after this failure.

  Export byte-identity diff: NOT RUN after the failed check. The pre-refactor source is saved as `app/checks/export_before.py` for comparison. The test run's bundles use `design: default`, whereas the current export entrypoint selects only `design: agent`; a valid comparison will need to account for that without modifying test bundles or changing export behavior.

  Final phase 1 rerun: PASS. `python app/checks/overlay.py`: 32 dimensions match, 328 blocks, 4 saved previews. `factory lint <attempt3>`: exit 0, 0 findings. `python app/checks/export_diff.py`: direct `process()` calls on all four default-design bundles, 32 pages, 100 output files, 0 differing bytes. Temporary output folders were removed automatically. Baseline reads use UTF-8 in the harness; PDF bytes are replayed across both implementations to eliminate Chromium timestamp variability. Geometry and PNGs are independently captured. Earlier C013 findings were caused by the same Windows decoding bug: HEAD produces 12 findings with cp1252 and 0 with UTF-8. They are resolved encoding issues.

## Phase 2: read-only viewer

- [x] `app/server`: FastAPI, scan a run folder, `GET` routes for runs, docs, pages, image, html [3, 4]
- [x] `app/web`: Vite + React + TS; typed client generated from OpenAPI [3]
- [x] Queue screen with filters and sort (no review data yet) [6]
- [x] Page review: rail, image, boxes, reading-order path, toggles, zoom; inspector Block, Lint, Document tabs [6]
- [x] Refuse to draw when the boxes' image size and the PNG differ [9]
- [x] `app/run.ps1 <run folder>` [3]
- [x] **Check:** open every page of the attempt3 run; no box misplaced; split blocks and spreads display correctly

  Interim check: API TestClient read all 4 subset-scoped documents and 32 pages; all dimensions matched. `npm run generate` and `npm run build` passed. Browser connector inventory was empty, so local Playwright smoke test `python app/checks/viewer.py` passed (SVG polygons drawn; Tab/J navigation), screenshot `app/checks/viewer.png`. Full every-page visual inspection and synthetic spread/mismatch checks remain pending.

  Phase 2 check: PASS for all 32 supplied pages. `python app/checks/all_pages.py` opened every page through the UI, verified expected polygon counts, saved 32 page screenshots and `all_pages.png`, and injected a dimension mismatch to verify an alert and zero SVG overlays. Initial screenshot check raced page replacement (`Element is not attached`); fixed by waiting for the page response and image readiness, then reran successfully. Contact sheet inspected: boxes align with content including split pieces. No supplied spread fixture exists; synthetic spread check remains a limitation.

## Phase 3: verdicts and decisions

- [x] Review file model and storage in `reviews/{doc_id}.json`, append-only history [5]
- [x] Block verdicts (`1`–`6`), page decisions (`A`/`F`/`R`), notes [5, 6]
- [x] Derived document status; queue totals and progress [5, 6]
- [x] Version check on writes; conflict message [4]
- [x] Stale review when `bundle_hash` changes [7]
- [x] Full keyboard flow [6]
- [x] **Check:** review one whole document using only the keyboard; kill the server mid-review and reload, nothing lost

  Result: PASS. `python app/checks/reviews.py`: 10 pages, 20 persisted changes, 10 stale-version conflicts, approved status and 4 subset-isolated review paths. Initial script import failed (`No module named app`); added workspace root to script path and reran. `python app/checks/keyboard_restart.py`: 10 pages reviewed with 1/A/J keys, 20 history entries survived forced process termination and fresh server startup. Test-created review removed afterward. Build/type generation passed after correcting npm working directory. Full status/reviewer filters remain a UI gap to finish.

## Phase 4: corrections

- [x] Redraw a box (`Shift+drag`), change category and attributes [5]
- [x] Drag-to-reorder reading order; path follows [6]
- [x] Text issue verdict flags the document; source text is never edited or applied by export (updated scope) [5]
- [x] **Check:** corrections round-trip through the review file and display on reload

  Result: correction API round-trip PASS. Extended `python app/checks/reviews.py` to save a corrected polygon/category/attributes and reversed reading order, then read through a fresh client and verify exact persisted values. Frontend supports Shift+drag rectangle replacement and drag-to-reorder; builds passed. Text editing remains excluded by the updated prompt; `text_wrong` verdict derives flagged status without altering source text. UI correction gestures still need browser regression coverage.

## Phase 5: factory integration

- [x] `factory export` includes only approved documents and applies box, category, attribute and order fixes; `--include-unreviewed` [7]
- [x] `factory reviews report <run>` [7]
- [x] Lint failures screen and Export screen, using the existing screen layout (updated scope: no new design file) [6]
- [x] **Check:** export a run with 3 approved, 1 corrected, 1 rejected document; the corrected box appears in `dataset.json`, the rejected document does not

  Result: PASS. `python app/checks/export_reviewed.py` used temporary copies of the supplied bundles plus a fifth subset copy: 3 plain approved, 1 corrected approved, 1 rejected. Full export wrote 4 documents / 32 pages / 328 blocks. Assertions verified corrected polygon, category, attributes, and reversed reading order in dataset.json, and omission of the rejected subset. Temporary copies, output and test reviews were removed. No test bundle content was edited or regenerated. `factory reviews report <attempt3>` reports 4 todo after test cleanup. `python -m pytest OCR_VLM_benchmark_factory/tests/test_reviews.py -q`: 3 passed (approval coverage, text flags, stale exclusion). `python app/checks/conflict_ui.py`: visible two-tab 409 conflict and both new screens rendered. `npm run generate`, `npm run typecheck`, and `npm run build`: passed. Type checking initially exposed tuple widening from the client response types; explicit generated-schema response casts fixed it, without handwritten API types.

## Earlier work report (superseded by final report below)

- Built: shared export-compatible capture module; typed sidecar models; recursive boxes/lint CLI backfill; generation hooks; contract 0.3.0 documentation and compatibility with existing 0.2.0 bundles. Backfill produced 4 boxes sidecars and 4 lint sidecars.
- Checks: boxes command passed (4 documents / 32 pages / 328 blocks); lint returned 12 findings and exit 1; visual overlay check failed on Windows decoding before producing any image; export byte comparison not run. Phase 2 and phase 3 checks were not run because phase 1 did not pass.
- Known gaps: sidecar/refactor tests and export identity proof remain outstanding; Windows UTF-8 reads need attention; stored C013 mismatches need investigation without changing bundle content. The four subsets reuse the same doc_id, so the future server must scope document lookup and reviews by subset/run to avoid collisions.
- App/design: phases 2–3 have not started; no viewer, server, review storage, or launcher exists yet. Neither design screen has been implemented or visually verified. Corrections, export integration, Lint failures and Export screens remain untouched.

## Resumed validation

Updated instructions supersede the earlier stop-on-failure workflow. Fixed implicit Windows decoding in the touched linter/export modules and added `app/checks/overlay.py` with explicit UTF-8 reads. Ran `.venv/Scripts/python.exe app/checks/overlay.py` from the workspace with the factory Python path: PASS, 32 image dimensions matched, 328 blocks counted, 4 first-page overlays generated. Inspected en_long preview: rectangles align with the rendered text. Reran `factory lint OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3`: exit 0. Compared the saved pre-refactor CAPTURE JavaScript with the shared module via Python AST: byte-identical. This source comparison does not replace the required complete export-output diff; that check remains outstanding. Phases 2–5 remain unimplemented and unchecked.

## Final report (2026-11-06)

Built all five phases: factory sidecars and shared capture; FastAPI bundle API and generated TypeScript client; queue and SVG page viewer; atomic subset-scoped reviews with history and optimistic concurrency; box/category/attribute/order corrections; approved-only factory export, review reporting, and Lint/Export screens. `app/run.ps1 <run folder>` was exercised successfully and the app is serving at http://127.0.0.1:8765. Usage is in README.md.

Check results:

- Phase 1: 4 documents / 32 pages / 328 blocks backfilled; 0 current lint findings; 4 overlay previews saved. Direct pre/post export comparison: 100 files, 0 differing bytes. PDF bytes replayed to control creation timestamps; independently generated PDF timestamps are not claimed identical. Earlier C013 observations were caused by the same Windows decoding bug: HEAD produces 12 findings with cp1252 and 0 with UTF-8; these are resolved encoding issues.
- Phase 2: all 32 supplied pages opened in the browser with expected polygon counts; screenshots and contact sheet saved. Mismatched dimensions produced an alert and zero SVG. Synthetic spread check passed with doubled width and correctly positioned right-leaf polygons. Split pieces were inspected in the all-page contact sheet. Initial screenshot race was fixed by awaiting page/image readiness.
- Phase 3: 10-page keyboard review / 20 changes survived forced termination and a fresh server process. Ten stale-version API writes returned conflicts; two actual browser tabs showed a visible 409 message. Four identical doc_ids remain isolated by subset. Queue progress derives from review pages; persisted document status is recalculated on each write.
- Phase 4: polygon/category/attribute/order data round-tripped through JSON; browser Shift+drag, category blur-save and drag reorder survived reload. Text-wrong flags status; no source-text editing is provided.
- Phase 5: 5-document temporary fixture exported 4 approved / 32 pages / 328 blocks, including corrected geometry, category, attributes and order; rejected document absent. Factory review tests: 3 passed. OpenAPI generation, TypeScript checking, production build and launcher passed.

Known gaps and design differences: the viewer uses real thumbnails and fits pages to available height/width; the inspector scrolls for long content. Category and attribute correction controls use validated text/JSON inputs rather than the design's specialized dropdowns, so the entire taxonomy remains available without custom widgets. Queue progress is numeric rather than miniature segmented bars. Some decorative icons, lint/statistic sublabels, and the category legend are not reproduced. Document details expose manifest, brief and raw trace rather than a dedicated cost/retry summary. The app uses one server process (as launched); its in-process write lock is not designed for multiple uvicorn workers. Stale reviews are preserved and refused on write; there is no reset/archive UI yet. The launcher currently rebuilds on every invocation. No source document bundle content was edited, and existing unrelated factory work was preserved.


## Round 2 ? factory integration fixes (2026-11-06)

- [x] Corrected Phase 1's C013 interpretation: HEAD's 12 cp1252 findings and zero UTF-8 findings are the same resolved decoding bug, not separate factory extraction issues.
- [x] Audited Python text I/O in factory/, tests/, app/server and app/checks. All file text reads/writes now state UTF-8; AST audit reports **0 missing encodings**, saved in factory `.doc_local/leverage_uniqueness/runs/round2_encoding.json`.
- [x] Restored the language-balance gate for approved-only and include-unreviewed export; `--allow-imbalance` bypasses it in both paths.
- [x] Both modes recursively discover subset bundles and prefix image, Markdown, PDF and source-content names by subset. The `design == agent` restriction remains for the flat include-unreviewed layout; subset fixtures remain eligible. Three new `tests/test_round2_export.py` regressions cover both gate modes, subset name collisions, the flat filter and unapproved exclusion.
- [x] Plain-Windows regression runs use no `-X utf8` or `PYTHONUTF8`. Initial plain run: 38 passed / 9 setup errors caused by access to the shared pytest temp directory. Workspace-local temp/cache rerun: 47 passed. Expanded suite later passed 55 tests; final log is factory `.doc_local/leverage_uniqueness/runs/round2_pytest.log`. Command: `.venv/Scripts/python.exe -m pytest -q --basetemp .work/round2_final55_checked -o cache_dir=.work/round2_cache` (from factory root).

No existing bundle under out/**/documents/** was edited, no v1 bank files were changed, and no live model calls were made.

Final Part A regression result: **55 passed**, 17 existing Pillow deprecation warnings, **92.16s**; zero missing text encodings.

Round 2 resume validation: plain `.venv/Scripts/python.exe -m pytest -q` from the factory root: **60 passed, 18 warnings, 100.36s** (workspace-local TEMP/TMP/TMPDIR; no UTF-8 override). The 18 warnings are 17 existing Pillow deprecations and one pytest cache-permission warning. Live commands were checked with CLI help only; no model calls or production bundle edits.
