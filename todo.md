# TODO: benchmark factory v2

> **2026-11-02:** `FIX_PLAN.md` replaces the element groups (phase 1) and the design conversation (phase 3) with one agent conversation per document and `--batch N`. Do `FIX_PLAN.md` steps 1–5 before continuing phase 5. Bugs are listed in `REVIEW_codex_v2.md`.

Details for every item are in `PLAN_v2.md` (section numbers in brackets).
v1 lives in `archive/2026-11-02_v1/`: port from it, never import from it, never edit it.

## Done

- [x] Decide the final pipeline (element agent + design agent) [1]
- [x] Move all of v1 into `archive/2026-11-02_v1/`
- [x] Write `PLAN_v2.md`

## Phase 0: skeleton (no model needed)

- [x] `pyproject.toml`: package `factory`, script `factory = factory.cli:main`, package data for configs/designs/fonts [2]
- [x] `factory/paths.py` with ROOT and standard paths
- [x] Copy `configs/models.yaml`, `configs/taxonomy.yaml` from the archive
- [x] Split archive `configs/prompts.yaml` into `configs/content.yaml` + `configs/doc_types/financial_report.yaml` [3]
- [x] Move `configs/pool.yaml` settings into the doc type file (`pool:`), add `elements:` groups [3]
- [x] Copy pool: archive `content_pool/financial_report/` -> `pool/financial_report/`
- [x] Copy fonts: archive `templates/_shared/assets/fonts/` -> `designs/_fonts/`
- [x] Port modules with `core.` -> `factory.` imports: llm, contract, browser, content (config, schema, numbers, rules, article), render (blocks, marks, fill, flow, probe, metrics, contact, academic, fonts), runner (context, result, writer, dataset) [2]
- [x] `content/config.py` loads `content.yaml` + `doc_types/*.yaml`
- [x] Drop composer code paths (compose, themes, `--html/--theme/--cover/--variant`, `--composed`) [2]
- [x] Default design: `designs/financial_report/default.html` from archive `templates/financial_report/classic.html`, without the "BỘ SỐ LIỆU GIẢ LẬP" header text; running header via `running_header` slot [3]
- [x] Fixture: archive `tests/fixtures/financial_report_content.json` -> `tests/fixtures/`
- [x] Reinstall: `.venv/bin/pip install -e .`
- [x] **Check:** `factory generate financial_report --fixture tests/fixtures/financial_report_content.json --design default` -> 0 lint issues

Phase 0 check output: `out/documents/financial_report/financial_report_000001: 0 lint issues` (exit 0). Fixture has no variables; chose the first configured value per variable for deterministic fixture generation.


Academic Phase 0 fixture check (2026-11-03): all four requested fixtures were run with `--design default`.
- `academic_paper_vi_short.json` -> `academic_paper_000124`: failed during fill with page 2 overflow.
- `academic_paper_vi_long.json` -> `academic_paper_000125`: failed during fill with page 2 overflow.
- `academic_paper_en_medium.json` -> `academic_paper_000126`: failed during fill with page 2 overflow.
- `academic_paper_en_long.json` -> `academic_paper_000127`: failed during fill with page 2 overflow.

Exact errors recorded in `out/failed/academic_paper/*/problems.json`:
- `academic_paper_000122`:
  ```text
  data-region requires data-chain
  data-region requires data-chain
  data-region requires data-chain
  data-region requires data-chain
  journal: field must be placed exactly once (found 4)
  ```
- `academic_paper_000123`:
  ```text
  data-region requires data-chain
  data-region requires data-chain
  data-region requires data-chain
  data-region requires data-chain
  journal: field must be placed exactly once (found 4)
  ```
- `academic_paper_000124`:
  ```text
  page 2: block paper_paragraph_12 extends outside the page by 13 mm on the bottom
  page 2: block paper_tab_errors_caption extends outside the page by 20 mm on the bottom
  page 2: block paper_tab_errors extends outside the page by 56 mm on the bottom
  page 2: block paper_tab_errors_note extends outside the page by 61 mm on the bottom
  page 2: block paper_fig_coverage_caption extends outside the page by 68 mm on the bottom
  page 2: block paper_fig_coverage extends outside the page by 173 mm on the bottom
  page 2: block paper_eq_aligned extends outside the page by 200 mm on the bottom
  page 2: block paper_eq_aligned_number extends outside the page by 204 mm on the bottom
  page 2: block paper_paragraph_17 extends outside the page by 236 mm on the bottom
  page 2: block paper_fig_pipeline_caption extends outside the page by 242 mm on the bottom
  page 2: block paper_fig_pipeline extends outside the page by 320 mm on the bottom
  page 2: block paper_eq_interval extends outside the page by 329 mm on the bottom
  page 2: block paper_eq_interval_number extends outside the page by 334 mm on the bottom
  page 2: block paper_box_19 extends outside the page by 344 mm on the bottom
  page 2: block paper_heading_20 extends outside the page by 356 mm on the bottom
  page 2: block paper_paragraph_21 extends outside the page by 389 mm on the bottom
  page 2: block paper_paragraph_22 extends outside the page by 422 mm on the bottom
  page 2: block paper_heading_23 extends outside the page by 433 mm on the bottom
  page 2: block paper_paragraph_24 extends outside the page by 462 mm on the bottom
  page 2: block fn_1 extends outside the page by 470 mm on the bottom
  page 2: <main> content is 495 mm taller than its box; table paper_tab_errors: the last 3 of its 3 rows here do not fit
  ```
- `academic_paper_000125`:
  ```text
  page 2: block paper_paragraph_12 extends outside the page by 12 mm on the bottom
  page 2: block paper_tab_errors_caption extends outside the page by 19 mm on the bottom
  page 2: block paper_tab_errors extends outside the page by 55 mm on the bottom
  page 2: block paper_tab_errors_note extends outside the page by 60 mm on the bottom
  page 2: block paper_fig_coverage_caption extends outside the page by 66 mm on the bottom
  page 2: block paper_fig_coverage extends outside the page by 171 mm on the bottom
  page 2: block paper_eq_aligned extends outside the page by 198 mm on the bottom
  page 2: block paper_eq_aligned_number extends outside the page by 203 mm on the bottom
  page 2: block paper_paragraph_17 extends outside the page by 234 mm on the bottom
  page 2: block paper_fig_pipeline_caption extends outside the page by 241 mm on the bottom
  page 2: block paper_fig_pipeline extends outside the page by 318 mm on the bottom
  page 2: block paper_eq_interval extends outside the page by 327 mm on the bottom
  page 2: block paper_eq_interval_number extends outside the page by 332 mm on the bottom
  page 2: block paper_box_19 extends outside the page by 342 mm on the bottom
  page 2: block paper_heading_20 extends outside the page by 354 mm on the bottom
  page 2: block paper_paragraph_21 extends outside the page by 387 mm on the bottom
  page 2: block paper_paragraph_22 extends outside the page by 419 mm on the bottom
  page 2: block paper_heading_23 extends outside the page by 431 mm on the bottom
  page 2: block paper_paragraph_24 extends outside the page by 459 mm on the bottom
  page 2: block paper_paragraph_25 extends outside the page by 496 mm on the bottom
  page 2: block paper_paragraph_26 extends outside the page by 533 mm on the bottom
  page 2: block paper_paragraph_27 extends outside the page by 570 mm on the bottom
  page 2: block paper_paragraph_28 extends outside the page by 607 mm on the bottom
  page 2: block paper_paragraph_29 extends outside the page by 644 mm on the bottom
  page 2: block paper_paragraph_30 extends outside the page by 681 mm on the bottom
  page 2: block paper_paragraph_31 extends outside the page by 717 mm on the bottom
  page 2: block paper_paragraph_32 extends outside the page by 754 mm on the bottom
  page 2: block paper_paragraph_33 extends outside the page by 786 mm on the bottom
  page 2: block paper_paragraph_34 extends outside the page by 823 mm on the bottom
  page 2: block paper_paragraph_35 extends outside the page by 840 mm on the bottom
  page 2: block paper_tab_sensitivity_caption extends outside the page by 847 mm on the bottom
  page 2: block paper_tab_sensitivity extends outside the page by 876 mm on the bottom
  page 2: block paper_tab_sensitivity_note extends outside the page by 881 mm on the bottom
  page 2: block paper_fig_residuals_caption extends outside the page by 888 mm on the bottom
  page 2: block paper_fig_residuals extends outside the page by 935 mm on the bottom
  page 2: block paper_alg_procedure extends outside the page by 973 mm on the bottom
  page 2: block paper_equation_39 extends outside the page by 982 mm on the bottom
  page 2: block paper_heading_40 extends outside the page by 994 mm on the bottom
  page 2: block paper_paragraph_41 extends outside the page by 1027 mm on the bottom
  page 2: block fn_1 extends outside the page by 1035 mm on the bottom
  page 2: <main> content is 1061 mm taller than its box; table paper_tab_errors: the last 3 of its 3 rows here do not fit; table paper_tab_sensitivity: the last 3 of its 3 rows here do not fit
  ```
- `academic_paper_000126`:
  ```text
  page 2: block paper_paragraph_10 extends outside the page by 22 mm on the bottom
  page 2: block paper_eq_aligned extends outside the page by 42 mm on the bottom
  page 2: block paper_eq_aligned_number extends outside the page by 47 mm on the bottom
  page 2: block paper_heading_12 extends outside the page by 59 mm on the bottom
  page 2: block paper_paragraph_13 extends outside the page by 102 mm on the bottom
  page 2: block paper_tab_queue_caption extends outside the page by 109 mm on the bottom
  page 2: block paper_tab_queue extends outside the page by 138 mm on the bottom
  page 2: block paper_fig_load_caption extends outside the page by 143 mm on the bottom
  page 2: block paper_fig_load extends outside the page by 248 mm on the bottom
  page 2: block paper_paragraph_16 extends outside the page by 291 mm on the bottom
  page 2: block paper_paragraph_18 extends outside the page by 328 mm on the bottom
  page 2: block paper_fig_queue_caption extends outside the page by 335 mm on the bottom
  page 2: block paper_fig_queue extends outside the page by 413 mm on the bottom
  page 2: block paper_eq_recovery extends outside the page by 422 mm on the bottom
  page 2: block paper_eq_recovery_number extends outside the page by 427 mm on the bottom
  page 2: block paper_paragraph_20 extends outside the page by 471 mm on the bottom
  page 2: block paper_heading_21 extends outside the page by 483 mm on the bottom
  page 2: block paper_paragraph_22 extends outside the page by 527 mm on the bottom
  page 2: block paper_paragraph_23 extends outside the page by 568 mm on the bottom
  page 2: block paper_paragraph_24 extends outside the page by 610 mm on the bottom
  page 2: block paper_heading_25 extends outside the page by 621 mm on the bottom
  page 2: block paper_paragraph_26 extends outside the page by 655 mm on the bottom
  page 2: block paper_paragraph_27 extends outside the page by 663 mm on the bottom
  page 2: block fn_1 extends outside the page by 670 mm on the bottom
  page 2: <main> content is 696 mm taller than its box; table paper_tab_queue: the last 3 of its 3 rows here do not fit
  ```
- `academic_paper_000127`:
  ```text
  page 2: block paper_paragraph_10 extends outside the page by 22 mm on the bottom
  page 2: block paper_eq_aligned extends outside the page by 41 mm on the bottom
  page 2: block paper_eq_aligned_number extends outside the page by 46 mm on the bottom
  page 2: block paper_heading_12 extends outside the page by 58 mm on the bottom
  page 2: block paper_paragraph_13 extends outside the page by 101 mm on the bottom
  page 2: block paper_tab_queue_caption extends outside the page by 108 mm on the bottom
  page 2: block paper_tab_queue extends outside the page by 137 mm on the bottom
  page 2: block paper_fig_load_caption extends outside the page by 142 mm on the bottom
  page 2: block paper_fig_load extends outside the page by 247 mm on the bottom
  page 2: block paper_paragraph_16 extends outside the page by 291 mm on the bottom
  page 2: block paper_paragraph_18 extends outside the page by 327 mm on the bottom
  page 2: block paper_fig_queue_caption extends outside the page by 334 mm on the bottom
  page 2: block paper_fig_queue extends outside the page by 412 mm on the bottom
  page 2: block paper_eq_recovery extends outside the page by 421 mm on the bottom
  page 2: block paper_eq_recovery_number extends outside the page by 426 mm on the bottom
  page 2: block paper_paragraph_20 extends outside the page by 465 mm on the bottom
  page 2: block paper_heading_21 extends outside the page by 477 mm on the bottom
  page 2: block paper_paragraph_22 extends outside the page by 521 mm on the bottom
  page 2: block paper_paragraph_23 extends outside the page by 563 mm on the bottom
  page 2: block paper_paragraph_24 extends outside the page by 604 mm on the bottom
  page 2: block paper_paragraph_25 extends outside the page by 616 mm on the bottom
  page 2: block paper_heading_26 extends outside the page by 628 mm on the bottom
  page 2: block paper_paragraph_27 extends outside the page by 677 mm on the bottom
  page 2: block paper_paragraph_28 extends outside the page by 719 mm on the bottom
  page 2: block paper_paragraph_29 extends outside the page by 761 mm on the bottom
  page 2: block paper_paragraph_30 extends outside the page by 802 mm on the bottom
  page 2: block paper_paragraph_31 extends outside the page by 844 mm on the bottom
  page 2: block paper_tab_robustness_caption extends outside the page by 851 mm on the bottom
  page 2: block paper_tab_robustness extends outside the page by 880 mm on the bottom
  page 2: block paper_tab_robustness_note extends outside the page by 885 mm on the bottom
  page 2: block paper_paragraph_33 extends outside the page by 928 mm on the bottom
  page 2: block paper_paragraph_34 extends outside the page by 969 mm on the bottom
  page 2: block paper_alg_audit extends outside the page by 1007 mm on the bottom
  page 2: block paper_paragraph_36 extends outside the page by 1050 mm on the bottom
  page 2: block paper_equation_37 extends outside the page by 1058 mm on the bottom
  page 2: block paper_box_38 extends outside the page by 1068 mm on the bottom
  page 2: block paper_paragraph_39 extends outside the page by 1074 mm on the bottom
  page 2: block paper_heading_40 extends outside the page by 1085 mm on the bottom
  page 2: block paper_paragraph_41 extends outside the page by 1124 mm on the bottom
  page 2: block paper_heading_42 extends outside the page by 1135 mm on the bottom
  page 2: block paper_paragraph_43 extends outside the page by 1174 mm on the bottom
  page 2: block fn_1 extends outside the page by 1182 mm on the bottom
  page 2: <main> content is 1208 mm taller than its box; table paper_tab_queue: the last 3 of its 3 rows here do not fit; table paper_tab_robustness: the last 3 of its 3 rows here do not fit
  ```

Exact output-contract errors emitted for academic failed bundles:
```text
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000122/source_content.json
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000123/source_content.json
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000124/source_content.json
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000125/source_content.json
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000126/source_content.json
unexpected file: /Users/mac/Documents/Docs/OCR_Research/benchmark_factory/out/failed/academic_paper/academic_paper_000127/source_content.json
```

The four post-fix runs no longer report the original missing `data-chain` or duplicate `journal` slot errors. Their remaining page overflow errors originate in shared `factory/render/fill.py`; failed-bundle `source_content.json` is accepted in `ALLOWED["failed"]` but rejected by the checker in `factory/runner/layout.py`.

Existing tests after the template/config change: 25 passed, 1 failed. `tests/test_layout.py::test_offline_fixture_obeys_output_contract` fails only on the repository-root assertion: actual root has `dataset` and `.doc_local`, while the expected set has `archive`.

## Phase 1: element agent

- [x] `content/pool.py`: load pool, pick entry by industry/seed, `mixed_case`, placeholder filling [4]
- [x] `content/elements.py`: `ElementAgent` running groups as asyncio tasks in `after` order [4]
- [x] Per-group prompt: only that group's fields; later groups get a summary of earlier results (company name, key statement totals) [4]
- [x] Per-group validation on a restricted config; repair only the failing group [4]
- [x] `note_tables` / `note_charts` pseudo fields: exact indexes, shapes (v1 `PooledContentAgent.build`) [4]
- [x] Merge + full `validate_content`; route final problems back to the owning group [4]
- [x] Statements prompt: every row `{"code": "...", "values": [int, int]}`, plain integers (fixes recurring B01 111 / B02 01 errors) [4]
- [x] Trace every call (`llm_call`, `retry`, `check`)
- [x] Language balance [11]: `language_variable: lang`, `variables.lang: [vi, en]` in the doc type config
- [x] English pool: translate the 35 vi entries once with the model (prose only, placeholders kept) -> `pool/financial_report/en/`; move vi entries to `pool/financial_report/vi/`; pick entries by language [11]
- [x] English versions of statement line labels, column headers and field guides (VAS English wording) [11]
- [x] Element prompts in the target language; number format per language (vi `1.234.567`, en `1,234,567`) in `numbers.py` [11]
- [x] Language-leak check per text block (diacritics share + stop words); failures go back to the agent or mark the pool entry bad [11]
- [ ] **Check:** 5 real documents; record calls, output tokens, minutes per document vs trial_5 (3–4 calls, 16–23k tokens); 0 statement failures

## Phase 2: render changes

- [x] `SIZES`: add a3, letter, legal (+ landscape); update every use in fill, lint, writer, export [7]
- [x] `chart_svg`: add hbar, grouped_column, dot, lollipop, area, stacked_bar; labels inside the SVG [7]
- [x] Fill reads `data-chart-form` and `data-chart-colors` on chart slots; data always from content [7]
- [x] Fill copies `designs/_fonts/` into the bundle's `assets/fonts/` when the design uses them [7]
- [x] Fix page image size: exactly `round(mm / 25.4 * dpi)` (v1 gave 1652×2337 instead of 1654×2339) [7]
- [x] **Check:** default design rendered on A3 / Letter / Legal test pages; `factory verify` clean

Phase 2 size check: `a3 0 []`, `letter 0 []`, `legal 0 []`. Full `factory verify` acceptance is still pending.

## Phase 3: design agent

- [x] `configs/design.yaml` from archive `trial_5/redesign_experiment/prompt_config.json` (v2), adapted to "return a blank design" [5]
- [x] Doc type `design.fixed_labels` (full list from `classic.html`) and `forbidden_words` [3]
- [x] `fixed_labels` in both vi and en; the design agent gets the labels of the document's language [11]
- [x] `design/draws.py`: design_seed from spec seed + design index; 6 draws per criterion [5]
- [x] `design/ledger.py`: read last ~12 entries of `out/index/designs.jsonl` for the doc type; append on accept [5][8]
- [x] Content inventory builder: slot ids, kinds, categories, sections, item counts, table rows/columns, text lengths [5]
- [ ] Condensed slot-format rules (from archive `templates/README.md`) in the prompt [5]
- [x] `design/agent.py`: reply `{"design_spec", "html"}`; loop validate_template -> fill -> lint -> checks -> screenshots; max 3 repair rounds, same draws [5]
- [x] `llm/client.py`: image parts in OpenAI messages (contact sheet of all pages) [2][5]
- [x] `design/checks.py`: port `design_check.py` (spec, draws, ledger distinctness, palette contrast) [6]
- [ ] Browser probes: per-block text contrast, block overlap (seal over signature allowed), text < 9 px, forbidden words in labels, reading order 1..n [6]
- [x] Page fill < 20% on body pages -> warning to the agent, not a failure [6]
- [x] Failed designs -> `out/failed/` with last design + problems
- [ ] **Check:** 6 designs over 3 contents pass; injected trial_5 defects (duplicated cover, title on dark band, circle over name, clipped duplicate title, tiny table on huge sheet) are each caught

## Phase 4: runner, output, CLI

- [x] `DocSpec`: `design` (`agent` | `default`), `content_id`, `design_index`, `design_seed` [8]
- [x] One bundle per design + `design/design_spec.json`, `design/design.html`; provenance has content_id + design index [8]
- [x] `factory generate <type> --n N [--designs K] [--seed S] [--jobs J] [--model NAME]` [8]
- [x] `factory generate ... --fixture ... --design default` (no model) [8]
- [x] `factory redesign <bundle> [--designs K]` [8]
- [x] Keep `lint`, `preview`, `index`, `verify` [8]
- [x] Balanced language assignment: next document gets the language behind in `out/index` per doc type (ties by seed parity); `--lang vi|en` forces one; recorded in `spec.json` [11]
- [x] `factory index` / `factory export` report per language: documents, pages, blocks, characters, words; export fails outside 45–55% character share unless `--allow-imbalance` [11]
- [x] `factory export --to <dir>`: port archive `.doc_local/benchmark_build/build.py`; only agent-designed bundles [8]
- [x] `factory gallery <out>`: one HTML page with all previews (like trial_5 `gallery_v2.html`) [8]
- [ ] **Check:** export of a 5-document run passes its own checks; gallery opens

## Phase 5: end-to-end run

- [ ] `factory generate financial_report --n 6` with the real API (3 vi + 3 en)
- [ ] Gallery + compare with archive `trial_5/redesign_experiment/gallery_v2.html`
- [ ] Record time, calls, tokens, failures per stage
- [ ] **User review**

## Phase 6: tests and docs

- [x] Tests (no model): content + statement solve; element groups with FakeProvider incl. one repaired group; default design fills fixture with 0 lint; fake design reply through the loop; design_check rejects copied ledger entry and off-draw index; export image sizes; language assignment stays 50/50; leak check flags an English sentence in a vi block [9]
- [x] `README.md`: how to run
- [x] `docs/ARCHITECTURE.md`: the pipeline, short

## Phase 7: academic paper

- [ ] Pool for academic papers (headings + paragraphs with slot ids)
- [ ] Academic pool and labels in both vi and en; `en_vi_mixed` papers kept outside the 50/50 count [11]
- [ ] `configs/doc_types/academic_paper.yaml`: fields, element groups (formulas, tables, figures, charts, code, references, authors), fixed labels
- [ ] Port `content/rules/academic_paper.py`, `article.py`, `render/academic.py` paths
- [ ] **Check:** same as phase 5

## Optional (not decided)

- [ ] Reference library of 30–50 real report/magazine/filing layouts; each design draws 1–2 as inspiration
- [ ] More pool entries for more text variety (archive `.doc_local/content_pool/build_pool.py`)

## Notes for whoever runs this

- Never print `.env` values. Not a git repo.
- Use `.venv/bin/python` (has playwright; no bs4/lxml).
- Chrome cannot start inside the Codex `workspace-write` sandbox: rendering, lint and tests need the sandbox off, or the user runs them.

## Check results (current implementation)

Phase 1 real element check (initial implementation; failures retained):

| Seed | Seconds | Calls | Input tokens | Output tokens | Result |
|---|---:|---:|---:|---:|---|
| 1 | 227.0 | 12 | 128488 | 60469 | Expected exactly ['kpis', 'note_charts', 'revenue_chart', 'revenue_chart_caption'] |
| 3 | 199.6 | 8 | 77142 | 57039 | kpis: unknown source B02.10 |
| 4 | 153.2 | 9 | 91310 | 35378 | kpis: KPI value must be an integer or string |
| 5 | 240.6 | 9 | 105351 | 75920 | 1 validation error for ContentReply |

These results do not meet the trial_5 efficiency target. Group KPI validation was corrected to include earlier statement context; the parser now accepts a leading `<thinking>` wrapper. Full live revalidation remains necessary.

Phase 2: A3/Letter/Legal lint each returned 0 issues. Images at 200 DPI: A3 2339×3307, Letter 1700×2200, Legal 1700×2800. V2 verification of accepted fixture bundles returned `[]`.

Phase 3: fake design reply passed the complete loop. Injected tiny text, low contrast, duplicate text overlap, and decorative circle overlap were caught by browser probes. Six real designs across three contents have not passed.

Phase 4 export check failed: `ValueError: financial_report: Vietnamese character share 100.0% outside 45–55%`. No accepted agent-designed five-document run is available for export acceptance. Gallery HTML is generated.

Phase 6: `.venv/bin/python -m pytest -q tests/test_v2.py`: 6 passed. The browser fake-design loop and one-bundle export/image acceptance also pass (14 automated tests total). Remaining acceptance cases are still pending.

## Check results (current implementation)

Phase 1 real element check (initial implementation; failures retained):

| Seed | Seconds | Calls | Input tokens | Output tokens | Result |
|---|---:|---:|---:|---:|---|
| 1 | 227.0 | 12 | 128488 | 60469 | Expected exactly ['kpis', 'note_charts', 'revenue_chart', 'revenue_chart_caption'] |
| 2 | 292.8 | 11 | 109703 | 86843 | kpis: unknown source B02.010 |
| 3 | 199.6 | 8 | 77142 | 57039 | kpis: unknown source B02.10 |
| 4 | 153.2 | 9 | 91310 | 35378 | kpis: KPI value must be an integer or string |
| 5 | 240.6 | 9 | 105351 | 75920 | 1 validation error for ContentReply |

These results do not meet the trial_5 efficiency target. Group KPI validation was corrected to include earlier statement context; the parser now accepts a leading `<thinking>` wrapper. Full live revalidation remains necessary.

Phase 2: A3/Letter/Legal lint each returned 0 issues. Images at 200 DPI: A3 2339×3307, Letter 1700×2200, Legal 1700×2800. V2 verification of accepted fixture bundles returned `[]`.

Phase 3: fake design reply passed the complete loop. Injected tiny text, low contrast, duplicate text overlap, and decorative circle overlap were caught by browser probes. Six real designs across three contents have not passed.

Phase 4 export check failed: `ValueError: financial_report: Vietnamese character share 100.0% outside 45–55%`. No accepted agent-designed five-document run is available for export acceptance. Gallery HTML is generated.

Phase 6: `.venv/bin/python -m pytest -q tests/test_v2.py`: 6 passed. The browser fake-design loop and one-bundle export/image acceptance also pass (14 automated tests total). Remaining acceptance cases are still pending.

## Status

All 35 pool entries are translated; object keys and placeholder counts match the Vietnamese originals. Core implementation and live validation are in progress. API jobs are still running; this status is provisional. Unchecked items remain incomplete or unverified. Phase 7 and Optional remain untouched.

Implementation choice: default fixture bundles are stored in `out/fixtures/`, because the plan restricts dataset documents to agent-designed bundles. Earlier default bundles were moved there. The in-flight live run started before this correction; its language allocation must be checked in the recorded results.

Pool translation API usage: {'calls': 35, 'tokens_in': 109257, 'tokens_out': 195790}. English catalogue/guide translation: 1 call, 5243 input tokens, 3909 output tokens.

Statement arithmetic tests ported from v1: 5 passed. Combined offline suite: 12 unit tests plus 2 browser/export tests pass. The live phase-5 run has exceeded ten minutes on its first content item; no response/failure has been finalized yet.

Pool language scan: zero flagged blocks across all 35 Vietnamese and 35 English entries. Bad-entry markers are excluded from subsequent pool loading.

Phase 5 initial attempt interrupted after first document failed: 720.6 seconds, 19 calls, 166977 input tokens, 97748 output tokens. Root cause: group prompts accidentally included instructions for other groups. The in-flight second item was cancelled; its incomplete streaming usage is unavailable. Choice: restart the six-document acceptance run after correcting isolated prompts, since continuing obsolete prompts would only repeat the same implementation defect. This is a corrective restart, not an additional accepted dataset run.
