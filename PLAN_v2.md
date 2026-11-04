# Plan: benchmark factory v2 (final pipeline)

Decided on 2026-11-02. This plan is meant to be carried out by a coding agent (Codex).
Everything from v1 is in `archive/2026-11-02_v1/` and must stay there, unchanged; port
code out of it, never import from it.

## 1. The pipeline

```
factory generate financial_report --n 5 [--designs K] [--seed S]

 1. Spec        seed -> variables (industry, size, year), content_id, design seeds
 2. Text        pool/<type>/*.json, no model: board/auditor/notes prose with placeholders
 3. Elements    ELEMENT AGENT (API model): tables, statements, charts, figures, formulas,
                code, short fields (names, dates, addresses). Never long prose.
                Several small calls, each validated and repaired on its own.
 4. Content     merge 2+3, fill placeholders, validate (numbers, statement ties, rules)
 5. Design      DESIGN AGENT (API model), K times with different random draws:
                returns design_spec.json + one blank HTML design (slots + CSS), no text
 6. Fill        existing v1 fill engine pours content into the design, splits pages,
                writes every label (data-gt-*), reading order from the design
 7. Check       template checks, contract lint, design checks, visual probes;
                problems + page screenshots go back to the design agent (<= 3 rounds)
 8. Save        out/documents/<type>/<doc_id>/ (one bundle per design); ledger entry
 9. Export      factory export -> OmniDocBench-style dataset (only designed bundles)
```

Decisions already made by the user:
- Both agents use the user's API (`.env`: `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
  `OPENAI_MODEL_NAME`, currently `gpt-5.6-luna`). No Codex/CLI in the pipeline.
- The design agent returns a blank design (HTML skeleton with slots + CSS), not a
  finished document; code fills it, so text and numbers can never drift.
- `--designs K`, default 1. With K > 1 the same content is laid out K times.
- The dataset holds only agent-designed bundles. One hand-written default design is
  kept for tests and as a no-model fallback.
- The Python package is renamed `core` -> `factory`. CLI command stays `factory`.
- **Language balance (whole system):** Vietnamese and English must be balanced in every
  document type and in the exported dataset, so raw OCR performance can be compared
  across languages. See section 11.

## 2. Target layout

```
benchmark_factory/
  archive/2026-11-02_v1/        v1, read-only (code, configs, templates, outputs, docs, trial_5)
  PLAN_v2.md                    this file
  README.md                     how to run (write at the end)
  docs/ARCHITECTURE.md          the pipeline above, kept short
  pyproject.toml                package "factory", script factory = factory.cli:main
  configs/
    models.yaml                 copy of v1 (model_env OPENAI_MODEL_NAME)
    taxonomy.yaml               copy of v1
    content.yaml                shared: system prompt, field_kinds, repair_rounds
    design.yaml                 design-agent prompt: criteria, randomness, distinctness, rules
    doc_types/financial_report.yaml   variables, prompt, fields, statements, pool, element groups,
                                      fixed labels for designs
    doc_types/academic_paper.yaml     ported later (phase 7)
  pool/financial_report/        35 entries copied from archive content_pool/financial_report/
  designs/
    _fonts/                     bundled OFL fonts (copy of archive templates/_shared/assets/fonts)
    financial_report/default.html     the no-model default design (from a v1 template)
  factory/
    paths.py                    ROOT and standard paths
    llm/client.py               port; add image parts for OpenAI messages (screenshots)
    contract/                   models/, taxonomy.py, extract.py, lint.py (port)
    browser/browser.py          port
    content/
      config.py                 load content.yaml + doc_types/*.yaml (port of v1 config.py)
      schema.py numbers.py rules/   port as is (rules/financial_report.py, rules/academic_paper.py)
      article.py                port (academic)
      pool.py                   pool loading, choice by industry/seed, placeholder filling
      elements.py               ElementAgent: grouped parallel calls (section 4)
    render/
      blocks.py marks.py fill.py flow.py probe.py metrics.py contact.py academic.py fonts/  (port)
    design/
      draws.py                  seeded random draws per criterion
      ledger.py                 read/append out/index/designs.jsonl
      agent.py                  DesignAgent (section 5)
      checks.py                 design_check + visual probes (section 6)
    runner/                     context.py result.py writer.py dataset.py export.py
    cli.py
  tests/                        small, fixture based, no model (section 9)
  out/                          generated, git-ignored
```

Do not port: `core/render/compose.py`, `core/render/themes.py`, the 23 hand-made
templates, `_layout.yaml`, `_covers/`, `_pages/`, `check-template --composed`, the
`--html/--theme/--cover/--variant` options. The design agent replaces all of them.

## 3. Config split (from archive `configs/prompts.yaml` + `configs/pool.yaml`)

- `configs/content.yaml`: `system`, `field_kinds`, `repair_rounds` from v1 prompts.yaml.
- `configs/doc_types/financial_report.yaml`: the v1 `documents.financial_report` block
  (variables, prompt, fields, statements) plus:

```yaml
pool:
  dir: pool/financial_report
  text: [board_paragraph, auditor_paragraphs, board_title, auditor_title, auditor_addressee]
  notes: notes                 # pool gives titles + paragraphs; agent gives note_tables/note_charts
  placeholders: {company: cover_company, auditor: auditor_firm, year: fiscal_year}
elements:                      # element-agent calls; a group starts after the groups in `after`
  - name: company
    fields: [running_header, running_footer, cover_logo, cover_company, cover_period, cover_address,
             cover_tax, directors_table, directors_caption, signature_date, signer_1_name,
             signer_2_name, signer_3_name, company_seal, auditor_firm, auditor_seal, auditor_date]
  - name: statements
    fields: [B01_date, B01_table, B02_date, B02_table, B03_date, B03_table]
  - name: charts
    after: [company, statements]
    fields: [revenue_chart, revenue_chart_caption, kpis, note_charts]
  - name: note_tables
    after: [company, statements]
    fields: [note_tables]
design:
  fixed_labels:                # static texts a design may print (data-label), per page role
    B01: ["BẢNG CÂN ĐỐI KẾ TOÁN", "Mẫu số B01-DN", "Đơn vị tính: VND"]
    # ... take the full list from archive templates/financial_report/classic.html
  forbidden_words: ["giả lập", "mô phỏng", "hư cấu", "placeholder", "lorem"]
```

The v1 hard-coded running header "BÁO CÁO TÀI CHÍNH · BỘ SỐ LIỆU GIẢ LẬP" must not
come back: running headers use the `running_header` slot, and the design check rejects
`forbidden_words` in any static label.

## 4. Element agent (`factory/content/elements.py`)

Generalise archive `core/content/pool.py` (`PooledContentAgent`) and `core/agent.py`.

1. Pick the pool entry: same industry if any, index `seed % len(candidates)`.
2. Pick chart notes: 4–6 note indexes (seeded), as in v1.
3. Run element groups as asyncio tasks in dependency order (company + statements in
   parallel, then charts + note_tables in parallel). Each call asks only for its group's
   fields as `{"values": {...}}`, with the field listing restricted to those fields.
   Later groups receive a short summary of earlier results (company name, B01/B02 key
   totals after `solve`) so charts and note tables stay consistent with the statements.
4. Validate each group with `validate_content` on a config restricted to the group's
   fields; repair only that group (up to `repair_rounds`). Pseudo fields `note_tables`
   and `note_charts` are checked by the v1 `build()` logic (exact indexes, shapes).
5. Merge: fill placeholders in pool prose (`{company}`, `{core}`, `{auditor}`,
   `{auditor_core}`, `{year}`, `{prev}`, `{next}` — see v1 `mixed_case`), join notes with
   their tables/charts, then run full `validate_content` once more (statement ties, KPI
   sources). If that fails, route each problem to the group owning the field and repair.
6. Trace every call (`llm_call`, `retry`, `check`) as v1 does.

Known v1 model errors to address in the statements prompt: "line 111 needs two integer
VND values" (B01) and "line 01 needs two integer VND values" (B02) recur — state
explicitly that every row is `{"code": "...", "values": [int, int]}` with plain integers
(no strings, no dots). Long single replies broke JSON often; small groups fix most of it.

Pool notes: v1 pool has 35 entries built by archive
`.doc_local/content_pool/build_pool.py` from 50 Codex contents. More entries for more
variety can be produced later the same way; not part of this plan.

## 5. Design agent (`factory/design/agent.py`)

Source of the prompt: archive `trial_5/redesign_experiment/prompt_config.json` (v2,
criteria-based) — the prompt the user approved. Move it to `configs/design.yaml`
(criteria, randomness, distinctness, preservation, acceptance) and adapt the parts
that assumed a workspace agent:

- Input to the model (one user message):
  - the criteria text and the RANDOM DRAWS (`draws.py`: `random.Random(design_seed)`,
    6 numbers per criterion, design_seed derived from spec seed + design index);
  - the DESIGN LEDGER: the last ~12 `design_spec` summaries for this doc type from
    `out/index/designs.jsonl` (chosen option per criterion, palette, fonts);
  - the design format rules: the v1 slot contract (archive `templates/README.md`:
    `section.page`, `data-page-role`, `data-size`, `data-slot`, `data-label`,
    `data-split="auto"`, `data-frame`, `data-item`, `data-order`, `data-continued`,
    `data-region`/`data-chain`, `{n}`/`{total}`), condensed;
  - the content inventory, not the content: every slot id with kind, category, section,
    item counts, table row/column counts and text lengths, so the agent can size pages;
  - the fixed labels per page role and the available fonts (only bundled fonts in
    `designs/_fonts/`, loaded with `@font-face url(assets/fonts/...)`; they must cover
    Vietnamese; keep `'Factory Serif', serif` as fallback);
  - chart forms the code can draw (section 7) and that colours go into `data-chart-colors`.
- Output (JSON): `{"design_spec": {...}, "html": "<!doctype html>..."}`. design_spec
  keys as in the experiment: seed, draws, and for layout/style/reading_order/orientation:
  options (>= 10), index, chosen, details; style also palette + fonts; orientation also
  sheet per page role; skipped.
- Reading order is expressed with DOM order + `data-order` and region chains; the agent
  never writes `data-gt-*`.
- Loop (max 3 repair rounds): validate_template -> fill with the real content -> lint ->
  design checks -> render screenshots. Send back the problem list and a contact sheet
  image of all pages (OpenAI image part). Keep the same draws and choices across rounds;
  the agent fixes, it does not start over.
- On final failure the document goes to `out/failed/` with the last design and problems.

## 6. Checks (`factory/design/checks.py`)

Port archive `trial_5/redesign_experiment/design_check.py` and add browser probes:

- spec complete; >= 10 distinct options per criterion; `chosen == options[index]`;
  `index == floor(draws[c][0] * len(options))` unless recorded in `skipped`;
- distinct from every ledger entry of the doc type: no identical chosen option on any
  criterion, accent hue gap >= 25°, no shared font family;
- background/ink contrast >= 4.5 (palette) and per text block in the browser (computed
  colour vs effective background);
- no two labeled blocks overlapping (except seal over signature);
- no text below 9 CSS px;
- each page's reading order is a permutation 1..n (already guaranteed by fill; assert);
- no `forbidden_words` in static labels;
- page fill (v1 `metrics.page_fill`): body pages under 20% fill are reported to the agent
  as warnings, not failures;
- the v1 lint (`factory/contract/lint.py`) and template validation stay as they are.

The trial_5 defects these must catch: duplicated cover block, title drawn over a dark
band (contrast), circle covering the company name (overlap), clipped duplicate title at a
page bottom (lint/overflow), tiny tables on huge sheets (font size / fill).

## 7. Render changes

- `render/blocks.py` `SIZES`: add `a3`, `a3_landscape`, `letter`, `letter_landscape`,
  `legal`, `legal_landscape` (mm). Check every use of `SIZES` and page width/height in
  fill, lint, writer and export.
- `render/marks.py` `chart_svg`: add forms `hbar`, `grouped_column`, `dot`, `lollipop`,
  `area`, `stacked_bar` next to bar/line/donut. A chart slot may carry
  `data-chart-form` and `data-chart-colors` (comma-separated hex); fill renders the
  chart from the content data with that form. Data, labels, units never come from the
  design. Donut only for one non-negative series. Labels must stay inside the SVG.
- Fonts: fill must copy `designs/_fonts/` into each bundle's `assets/fonts/` when the
  design uses them (v1 fill already copies template assets; point it at the design
  folder).
- Fix the v1 image size mismatch: pages render 1652×2337 px for A4 at 200 DPI while the
  verifier expects 1654×2339 (CSS px truncated before scaling). Make the renderer
  produce `round(mm / 25.4 * dpi)` exactly, for every sheet size.

## 8. Runner, output, CLI

- Spec: v1 `DocSpec` with `template` replaced by `design` (`agent` or `default`), plus
  `content_id`, `design_index`, `design_seed`.
- One bundle per design: `out/documents/<type>/<doc_id>/` (v1 writer layout: pages/,
  assets/, content.json, document.json, docir/pagination, spec.json, trace.json,
  previews/) plus `design/design_spec.json` and `design/design.html`.
  `document.json.provenance` records content_id and design index.
- Ledger: append to `out/index/designs.jsonl` after a design is accepted. Designs
  running at the same time do not see each other; acceptable.
- CLI:
  - `factory generate <type> --n N [--designs K] [--seed S] [--jobs J] [--model NAME]`
  - `factory generate <type> --fixture tests/fixtures/<type>_content.json --design default`
    (no model; for tests)
  - `factory redesign <bundle> [--designs K]` (new designs for existing content)
  - `factory lint <bundle>`, `factory preview <bundle>`, `factory index`, `factory verify`
  - `factory export --to <dir>`: port archive `.doc_local/benchmark_build/build.py`
    (OmniDocBench layout: dataset.json, images/, pdfs/, mds/, configs/end2end.yaml,
    metadata/, source_content/, README, VERSION, checksums). It is better than v1
    `core/runner/omnidocbench.py` (per-line text, split blocks, real layout attrs).
- `factory gallery <out>`: one HTML page of all bundles with previews (like
  `trial_5/redesign_experiment/gallery_v2.html`), for quick review.

## 9. Tests (keep few, no model)

- content: fixture validates; statement solve/ties (port v1 test_content*, numbers).
- elements: FakeProvider replies per group, incl. one broken reply repaired in its group only.
- design: default design fills the fixture with 0 lint issues; a fake design-agent reply
  goes through the loop; design_check rejects a copied ledger entry and an off-draw index.
- export: one bundle exports with image sizes matching the verifier.

## 10. Phases and acceptance

| Phase | Work | Done when |
|---|---|---|
| 0 | Skeleton: pyproject (`factory` package), configs split, port modules with `core.` -> `factory.` imports, delete composer paths, reinstall `.venv` (`pip install -e .`) | `factory generate financial_report --fixture ... --design default` gives 0 lint issues |
| 1 | Element agent with groups | 5 real documents: fewer retries and less time than trial_5 (v1 pooled: 3–4 calls, 16–23k output tokens, several minutes per call); 0 statement failures |
| 2 | Render changes: sizes, chart forms, fonts, exact image size | default design renders on A3/Letter/Legal test pages; `factory verify` clean |
| 3 | Design agent + checks + ledger | 6 designs over 3 contents pass all checks; the trial_5 defect types are caught when injected |
| 4 | CLI redesign/gallery/export | export of a 5-document run validates; gallery opens |
| 5 | Run 5 documents end to end, compare with trial_5 `gallery_v2.html` | user review |
| 6 | Docs: README, docs/ARCHITECTURE.md | — |
| 7 | Academic paper: pool + element groups (formulas, tables, figures, code) + fixed labels | same acceptance as phase 5 |

## 11. Language balance (vi / en)

Goal: the benchmark measures raw OCR on Vietnamese and on English equally, so every
document type and the final dataset hold the same share of each language.

- **Document language is a spec variable.** Every doc type config gets
  `language_variable: lang` with `variables.lang: [vi, en]` (v1 already supports
  `language_variable`; academic papers may keep `en_vi_mixed` as an extra, outside the
  50/50 count). Labels already carry `lang` per block.
- **Balanced assignment, not random.** The runner assigns languages so each run and the
  whole `out/` stay 50/50 per doc type: count accepted documents per (doc_type, lang) in
  `out/index` and give the next document the language that is behind (ties by seed
  parity). `--lang vi|en` can force one. Record the choice in `spec.json`.
- **Balance is measured in text, not only in documents.** English and Vietnamese
  versions of the same doc type can differ in length. `factory index` and `factory export`
  report per language: documents, pages, text blocks, characters and words of
  ground-truth text, per doc type and overall. The export fails (or warns, flag
  `--allow-imbalance`) when the character share of either language is outside 45–55%.
- **Everything with words exists in both languages:**
  - pool: `pool/<type>/vi/*.json` and `pool/<type>/en/*.json`. The English financial pool
    is made once by translating the 35 Vietnamese entries with the model (prose only,
    placeholders kept), stored as separate entries; a run picks an entry of its own
    language. Same rule for academic papers later.
  - statement line labels (B01/B02/B03 catalogue), column headers and fixed labels
    (`design.fixed_labels`) get `vi` and `en` versions in the doc type config (English
    VAS wording, e.g. "BALANCE SHEET", "Cash and cash equivalents", "Form B01-DN").
  - element-agent prompts and field guides get the target language; the agent writes
    names, addresses, captions and table text in that language (Vietnamese company names
    stay Vietnamese in English reports, as real English versions do).
  - number format follows the language: vi `1.234.567` / `(1.234)`, en `1,234,567` /
    `(1,234)`; `numbers.format_vnd` and `parse_vnd` take the language.
  - design agent: language-neutral, but it receives the fixed labels in the document's
    language, and the font check covers the characters of both languages.
- **Content checks per language:** a Vietnamese document must not contain English
  sentences and vice versa (v1 saw English leakage such as "prospectively" in a
  Vietnamese report). Add a simple check: share of words with Vietnamese diacritics per
  text block, and a small stop-word test for the other language; failures go back to the
  element agent (or, for pool text, mark the pool entry bad).

## 12. Notes for the implementing agent

- Never print or commit `.env` values. The repo is not a git repository.
- Use `.venv/bin/python` (has playwright; has no bs4/lxml — use the stdlib or the v1
  `contract/extract.py` parser).
- Chromium/Chrome cannot start inside the Codex `workspace-write` sandbox (seen in
  trial_5: SIGABRT). Rendering, lint and tests need a run with the sandbox off, or the
  user runs them.
- Model calls are slow (~30 tokens/s); streaming is required (v1 `call_openai` streams
  with a 30-minute timeout). Cache in `.cache/llm` is kept.
- Reference material in the archive:
  - pipeline/content: `core/agent.py`, `core/content/pool.py`, `configs/prompts.yaml`, `configs/pool.yaml`
  - engine: `core/render/fill.py`, `blocks.py`, `marks.py`, `flow.py`, `probe.py`, `templates/README.md`
  - default design candidates: `templates/financial_report/classic.html` (remove the
    "BỘ SỐ LIỆU GIẢ LẬP" header text)
  - design prompt and checks: `trial_5/redesign_experiment/{prompt_config.json, prepare_prompt.py,
    design_check.py, compare_content.py, run_pass.py, gallery_v2.html}`
  - export: `.doc_local/benchmark_build/build.py`
  - history and known problems: `.doc_local/content_generation/log.md`
- The 50-report dataset in `../benchmark/` (outside the repo) is v1 output; leave it.
