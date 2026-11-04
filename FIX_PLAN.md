# Fix plan: one agent per document, small context (2026-11-02)

This replaces `PLAN_v2.md` §4 (element groups) and the conversation part of §5 (design agent).
Everything else in `PLAN_v2.md` stays. `REVIEW_codex_v2.md` lists the bugs referred to here.

## 0. What actually went wrong (from the traces)

Failed content `f3c446` used 13 calls and 139k input tokens:

| Call | Tokens in | Tokens out | Result |
|---|---|---|---|
| statements ×3 | 3.7k, 5.1k, 7.0k | ~1.8k each | **invalid JSON** twice ("trailing characters", "expected `,`") |
| company | 9.9k | 4.8k | ok |
| charts ×3 | 1.1k, 10.9k, 11.1k | 0.9–2.4k | negative chart value; then "Expected exactly [keys]" |
| note_tables ×2 | 0.7k, 11.2k | 1.5k, 3.2k | **invalid JSON** once |
| design ×4 | 8.4k, 12.8k, **35.8k**, 21.2k | 4.1–8.2k | "kpis: a flowing item cannot fit on one page", never fixed |

So:
- **Errors came from three things:**
  1. The model often returns slightly broken JSON, even in short replies (a stray `}` at the end, a missing comma).
  2. Checks were too strict (exact key set, exact float draws).
  3. A fill error the agent can't act on.
- **The cost came from repairs:**
  - Every repair resends the whole conversation, including the old broken reply.
  - The design prompt carries the whole `design.yaml` (6k characters), the full default design (10k), the field listing and the inventory.
  - Repair rounds add a contact-sheet image and all earlier HTML replies.

  A small first call grows to 11–36k by its third attempt.
- **Fix both:** repair JSON locally without calling the model, make checks lenient where that is safe, and give the agent a short, stable context.

## 1. Target design

### One document = one agent conversation (default, `--batch 1`)

```
[system]  fixed rules: output format, slot format, criteria, randomness   ← identical for every
          document, so the provider can cache it (keep it first and byte-identical)
[user 1]  ELEMENTS task: variables, language, pool note titles, statement catalogue (codes only),
          what to return
[asst 1]  {"values": {...}}            → parse (with local JSON repair) → code checks per field
[user 2]  DESIGN task: draws, ledger summary (last 4), content inventory, fixed labels, fonts
[asst 2]  {"design_spec": {...}, "html": "..."}  → fill → render → checks
[repairs] only what failed: "resend B01_table" / "fix these 3 problems in the design"
```

- **Normal case: 2 calls per document.**
- **Repairs:**
  - Each repair turn sends the problems and asks only for the broken part (one field, or the changed design).
  - Before each call, the history is rebuilt as: system, user 1, the *current merged* elements (not the broken replies), user 2, the latest design and the problems.
  - Old replies are never resent.
- **Hard limit:** 2 element repairs and 2 design repairs. After that the document fails, with everything saved.

### Batch (`--batch N`, e.g. 6)

- **One conversation for N documents.**
  - Elements: still one turn per document in that conversation. One reply holding N documents' tables is too long and breaks.
  - Design: **one turn for all N**. It returns `{"designs": [{"doc": 1, "design_spec": ..., "html": ...}, ...]}`. The model sees all N together, so they differ from each other by construction. The ledger is still used against earlier batches.
- **History stays small:** after each document's elements are accepted, only a short summary of that document stays in the conversation (company, sizes, inventory).
- **Design repairs per document:** a failed design is repaired alone ("fix design for doc 3: ..."), not the whole batch.

## 2. Token budget per call (enforce in code, log in trace)

| Call | Input target | Input hard cap | Notes |
|---|---|---|---|
| system (cached) | ≤ 4k | 6k | rules only; no examples longer than 15 lines |
| elements | ≤ 6k | 9k | statement catalogue as `code: label` lines, no formulas, no field listing for pool fields |
| element repair | ≤ 3k + merged values summary | 9k | send only the failed fields' current values + problems |
| design | ≤ 8k | 12k | no default design HTML; condensed slot rules; inventory as a compact table |
| design repair | ≤ 10k | 16k | latest HTML + problems + 1 contact sheet (max 1600 px wide) |

The run fails loudly if a hard cap is exceeded, so the prompt can't silently grow again.
Record `tokens_in`, `tokens_out`, the call kind and the repair number per call in `trace.json` and `run_metrics.json`.

Target per document: **2–3 calls, ≤ 30k input, ≤ 25k output**. Today: 13 calls, 139k input.

## 2a. Output contract: the only files each phase may write

Codex left 9 kinds of extra output in `out/`:
- `phase1/*_trace.json` and `*_metrics.json`, `run_metrics.json`;
- `fake_design_check/`, `probe_defects/`, `size_checks/`, `export_check/.staging/`;
- `design_reply_N.json.txt`, `contact.png`, `page_fill.json`, `previews/` inside bundles;
- stale `.tmp/`.

It also left duplicate modules (`runner/omnidocbench.py` next to `runner/export.py`, and `runner/verify.py` next to
`dataset.verify`). From now on, every phase writes only what is listed here, and code enforces it.

### Pipeline output (`out/`)

```
out/
  documents/<type>/<doc_id>/        accepted bundle, exactly the files below
  failed/<type>/<doc_id>/           failed document, exactly the files below
  runs/<run_id>/run.json            one file per run (replaces run_metrics.json and phase1/)
  index/documents.jsonl             one line per accepted bundle
  index/designs.jsonl               design ledger
  index/languages.json              vi/en stats
  gallery.html                      rebuilt by `factory gallery`
  .tmp/                             staging; must be empty when a run ends
```

| Phase | Writes | Schema (pydantic model in `factory/contract/models/`) |
|---|---|---|
| 1. spec | `spec.json` | `DocSpec`: doc_id, doc_type, seed, lang, variables, content_id, design_index, design_seed, batch_id |
| 2–4. elements + content | `source_content.json` | `SourceContent`: variables, lang, pool_entry, values (merged, validated) |
| 5. design | `design/design_spec.json`, `design/design.html` | `DesignSpec`: seed, draws, layout/style/reading_order/orientation {options, index, chosen, details}, palette, fonts, pages, skipped |
| 6. fill | `pages/page_NNN.html`, `assets/`, `style.css`, `content.json` (DocIR), `pagination.json`, `document.json`, `extra/statements.json` | existing contract models |
| 7. check | nothing new: lint, design checks and page-fill numbers go into `trace.json` events | `Trace` |
| 8. save | `images/page_NNN.png` (200 DPI; the only page images, so no `previews/`), `trace.json` | `Trace` |
| run | `out/runs/<run_id>/run.json` | `RunRecord`: command, started, ended, per document {doc_id, lang, status, calls, tokens_in, tokens_out, seconds, stage of failure} |

A failed document has only `spec.json`, `trace.json`, `problems.json` (stage plus a problem list),
`replies/` (the last element reply and the last design reply, one file each, overwritten, never numbered),
and `design/design.html` if a design exists. Contact sheets and screenshots used for repairs live in
`.tmp/` and are deleted.

### Development output (Codex)

- **New files go only in** `factory/`, `configs/`, `designs/`, `pool/`, `tests/`, `docs/`, and the tick boxes in
  `FIX_PLAN.md` / `todo.md`. No new top-level files or folders, no scripts at the root, and no second module
  that does the same job as an existing one.
- **Checks and probes write to a pytest `tmp_path`** (or `.work/checks/`, deleted at the end), never to `out/`.
- **Keep the bundled set of files fixed:** one module per job. Merge `runner/omnidocbench.py` into `runner/export.py`,
  and `runner/verify.py` into `runner/dataset.py`. The English statement catalogue moves from
  `configs/doc_types/financial_report_en.json` into `financial_report.yaml` under `lang: {vi: ..., en: ...}`.

### Enforcement

- `factory/runner/layout.py`: `ALLOWED` for `out/` and for each bundle kind (accepted, failed), plus
  `check_tree(out)`. `factory generate` calls it at the end of every run and exits non-zero on any unexpected
  file or a non-empty `.tmp/`.
- `tests/test_layout.py`: the run produced by the offline fixture matches `ALLOWED` exactly, and the repo root
  holds only the expected entries (`archive configs designs docs factory pool tests out .cache .venv .env
  .env.example .gitignore pyproject.toml README.md PLAN_v2.md FIX_PLAN.md REVIEW_codex_v2.md todo.md`).
- Every JSON file in the table is written through its pydantic model (`model_dump_json`), never through a
  hand-built dict.

## 3. Changes (in order)

### Step 0: output contract and cleanup (do first)

- [x] Move the current `out/` to `archive/2026-11-02_v2_codex_attempt/out/` (the first v2 attempt's outputs, kept for the record).
- [x] Add `SourceContent`, `DesignSpec` and `RunRecord` models. Writers use them.
- [x] Remove the extra writes: `run_metrics.json`, `phase1/`, `design_reply_N.json.txt`, `contact.png`, `page_fill.json`,
      `previews/` in bundles. Page-fill numbers and lint issues go into `trace.json`.
- [x] Merge the duplicate modules (`omnidocbench.py` → `export.py`, `verify.py` → `dataset.py`) and move the English
      catalogue into the YAML.
- [x] `runner/layout.py` + `check_tree`, called at the end of `generate`. Add `tests/test_layout.py`.
- [x] Redirect every existing test and check that writes under `out/` to `tmp_path`.

**Check:** `pytest -q | tail -5` passes. A fixture run leaves only the files in the table above, and `.tmp/` is empty.

### Step 1: local JSON repair, retries, lenient parsing (`factory/llm/client.py`)

- [x] `parse_json`: before failing, try local fixes:
  - strip a Markdown fence;
  - cut trailing characters after the last balanced `}`;
  - remove trailing commas;
  - close unbalanced `]` `}` at the end.

  Only if that fails, ask the model, and then only "return valid JSON" with the parser error. Don't resend the content.
- [x] Request JSON mode when the endpoint supports it: `response_format={"type":"json_object"}` (OpenAI). Add a flag in `models.yaml` (`json_mode: true`). Gateway compatibility remains for Step 5.
- [x] Transport retries: 3 attempts with backoff for connection errors, 5xx and 429. Default `--jobs 2`.
- [x] Remove the Router's own schema-retry loop. The document agent owns repairs, so retries can't nest.

**Check:** feed the 3 broken replies saved in the failed traces (`out/failed/.../trace.json`, `retry` events) through `parse_json`. At least 2 of the 3 should parse locally.

**Execution note:** no tests were run, as requested. The archived trace examples were not inspected because the archive folder is off limits; gateway JSON-mode compatibility remains unverified until Step 5.

### Step 2: the document agent (`factory/agent.py`, replaces `content/elements.py` and the conversation in `design/agent.py`)

- [x] `DocumentAgent(config, variables, ctx, lang, design_seed, ledger)` with `elements()`, `design(content)` and a shared `history()` builder (section 1).
- [x] Elements prompt:
  - the requested field ids with one-line guides;
  - the statement catalogue as compact `code|level|label` lines in the document's language;
  - note titles with indexes;
  - the chart-note indexes;
  - the row rule ("values: [int, int]").
  - Leave out pool text and the full field_kinds dump.
- [x] Elements checks, per field:
  - ignore extra keys;
  - missing or invalid fields go into the repair list;
  - accepted fields are kept and never asked again.
- [x] Route repairs by `ContentError.problems` (`field: message`), not by substring matching.
- [x] `mixed_case` and company name: accept `CÔNG TY ...` in both languages. A bad name is a `cover_company` problem, repaired in the elements turn.
- [x] Delete the dead single-call prompt code in `content/pool.py`. The pool module only loads, chooses and fills placeholders.

**Check:** with a FakeProvider, one document with a broken `B01_table` gets repaired by resending only `B01_table`, and the logged input of the repair call is under 9k tokens.

**Execution note:** not run; this check invokes the document agent.

### Step 3: design turn (`factory/design/agent.py`, `configs/design.yaml`)

- [x] Rewrite `design.yaml` for a blank-design reply. Remove:
  - "update data-gt-ro" (reading order = DOM order, `data-order` and region chains);
  - "must_be_written_before_any_code";
  - "do not copy work folders";
  - `requested_model`.

  Keep criteria, randomness, distinctness and the design_spec keys. Target ≤ 3k characters.
- [x] Condensed slot-format rules (≤ 40 lines). Remove `reference_blank_design`. A minimal unstyled 1-page example (≤ 15 lines) is allowed.
- [x] Draws:
  - send them rounded to 4 decimals;
  - don't make the model echo them: code writes `seed` and `draws` into `design_spec` after the reply;
  - the check compares `index` with `floor(draw * len(options))` using the rounded draws.
- [x] Inventory as a compact table: `slot | kind | section | size` (e.g. `B01_table | statement | B01 | 52 rows × 5 cols`, `board_paragraph | text×8 | board_report | 95 words each`).
- [x] Ledger: last 4 entries only, each one line (`doc_id: layout / palette hexes / fonts / orientation rule / reading-order rule`). Store `doc_id` in `designs.jsonl`.
- [x] Distinctness (`design/checks.py`):
  - compare with the last 4 entries;
  - fonts as a *pairing* (heading + body), not single families;
  - accent hue gap ≥ 25° to the last 4 only.
- [x] Add 4–8 more OFL fonts with Vietnamese coverage to `designs/_fonts/` (with licences and `SOURCES.md`). Candidates: Inter, Roboto Slab, Source Serif 4, Montserrat, Merriweather, IBM Plex Sans/Serif. Check Vietnamese coverage with the existing font-coverage helper.
- [x] Check that `design_spec.orientation.pages` matches the `data-size` values in the HTML.
- [x] Make fill errors actionable (`render/fill.py`): include page role, region, item id, item height and region height in mm, and font size. For example: "kpis_3 is 180 mm tall; region `aside` on role board is 120 mm".

**Check:**
- A FakeProvider design reply with rounded draws passes.
- The 5 injected trial_5 defects are each reported.
- A 5th and a 13th design are not blocked by the distinctness rules.

**Execution note:** not run; these design checks invoke rendered agents/browser work. Font glyph coverage was checked directly with the existing helper.
The archive template README was not opened; the condensed format follows the rules already stated in this plan and the current template validator.

### Step 4: batch mode and CLI (`factory/cli.py`)

- [x] `--batch N` (default 1): N documents share one conversation (section 1). One design turn returns N designs, and failed designs are repaired one by one.
- [x] Fix the staging leak: failed designs move from `out/.tmp/<type>/<doc_id>` to `out/failed/<type>/<doc_id>` with every reply and `problems.json`.
- [x] Move check outputs out of `out/` (to `.work/checks/`); no diagnostic check artifacts are written under `out/` by the CLI.
- [x] Reformat `cli.py` and `agent.py` into normal readable code (no `a;b;c` one-liners).

**Check:** offline, `--batch 3` with a FakeProvider gives 3 documents from 1 design call, and a forced failure in design 2 repairs only design 2.

**Execution note:** not run; this check invokes document and design agents. A failed batch JSON-only repair is saved as a failure rather than triggering additional full design generations. Static parsing passed for the touched Python/YAML files; the design config is 2,636 characters with 9 slot-format lines, and all 10 default-template pages have `data-size`.

### Step 5: live runs (run these yourself, outside Codex)

- [ ] `factory generate financial_report --n 2 --jobs 2` (1 vi + 1 en). Expect 2–3 calls and ≤ 30k input per document.
- [ ] `factory generate financial_report --n 6 --batch 6`.
- [ ] Paste `out/run_metrics.json` and the gallery into `todo.md`.

## 4. Running this with Codex without burning quota

- **One step per session.** Steps 0–4 are five separate `codex exec` runs. Start each with: "Read FIX_PLAN.md step K only."
- **Use `gpt-5.6-luna` with `model_reasoning_effort="low"`.** Steps 1, 2 and 4 are mechanical. Use `gpt-6.1-sol` only if step 3 gets stuck.
- **Don't let Codex explore.** Say: "Edit only the files named in step K. Do not open `archive/` except the file named in the step. Use `| tail -30` on every test or log command. Never print HTML, JSON bundles or traces whole."
- **Don't let Codex run the live API.** Step 5 is yours. A live run inside Codex makes it poll, and each poll resends its context.
- **Turn off auto-review for these runs.**

Prompt for each session:

```
Read FIX_PLAN.md and do step K only. Edit only the files that step names. Do not ask questions;
if something is unclear, pick the option closest to the plan and note it under the item in
FIX_PLAN.md. Follow section 2a: create files only where it allows, write check output only to
pytest tmp_path, and leave no extra files. Use .venv/bin/python. Run the step's Check offline,
tick the items, then stop.
Never print .env, whole HTML/JSON files or traces; pipe command output through tail -30.
```
