# Review of Codex's v2 work (2026-11-02, ~01:20)

State reviewed: `factory/` (~5.7k lines), configs, `designs/`, `pool/`, `tests/`, `out/`.
Codex had edited files 5 minutes before this review, so some items may already be moving.

## Verdict

The skeleton is good and the offline path works: `pytest` gives 14 passed, the default design
fills the fixture with 0 lint issues, the 35 English pool entries exist, and the sizes and chart forms are in.
**The real pipeline has not produced one accepted document yet.** The phase 5 run failed
4 of 4 contents, and `out/documents/` is empty. Several of the ticked items are written but
not working (below). Phases 1, 3, 4 and 5 should not be counted as done.

Live results so far (`out/run_metrics.json`, `out/phase1/1_metrics.json`):

| Content | Calls | Tokens in / out | Time | Failure |
|---|---|---|---|---|
| phase 1 test | 12 | 128k / 60k | 227 s | "Expected exactly ['kpis','note_charts','revenue_chart','revenue_chart_caption']" |
| eed740 | 5 | 41k / 22k | 121 s | `'CÔNG TY '` (mixed_case KeyError) |
| d255e5 | 1 | 1k / 0.5k | 126 s | Connection error |
| 987312 | 1 | 1k / 0.5k | 126 s | Connection error |
| f3c446 | 13 | 139k / 42k | 262 s | design: "kpis: a flowing item cannot fit on one page" after 4 attempts |

The target was fewer calls and fewer tokens than v1 (3–4 calls, 16–23k out). This run used more.

## Blocking bugs (fix first)

1. **The distinctness check can't be satisfied after a few documents** (`factory/design/checks.py`).
   - It rejects any font shared with any of the last 12 ledger designs, but `designs/_fonts/`
     has only 4 families (Be Vietnam Pro, Lora, Noto Sans, Noto Serif). From the 5th design on,
     every design fails.
   - It also requires a ≥25° accent-hue gap to all 12 entries. That blocks up to 12 × 50° = 600° of
     a 360° wheel, so it is impossible after about 7 designs.
   - Fix: compare only with the last 3–4 entries for fonts (or compare font *pairings*, not single
     families), use a hue gap to the last 3–4 entries only, and add more OFL fonts with
     Vietnamese coverage (8–12 families).
2. **Exact float comparison of draws** (`design/agent.py`: `if reply.design_spec.get('draws')!=randoms`).
   - The model has to echo 24 floats such as `0.8372614893` exactly. Any rounding fails the
     whole attempt.
   - Fix: don't ask the model to echo the draws. Inject them into `design_spec` in code after the reply,
     and round draws to 4 decimals in the prompt.
3. **Failed designs stay in staging** (`cli.py`: `staging.glob(cid+'*')`).
   - Staging folders are named by doc_id (`financial_report_000002`), not content_id, so a failed
     design is never moved to `out/failed/`. `out/.tmp/financial_report/financial_report_000002`
     is still there now.
   - The failed folder ends up with only `trace.json`.
4. **English company names crash `mixed_case`** (`content/pool.py`).
   - The `'CÔNG TY '` failure means `LEGAL_CASE` lookups break on spacing or English
     legal forms.
   - The English path needs its own rule: either keep Vietnamese legal names, as the plan says,
     and make the agent always write `CÔNG TY ...`, or support "... JOINT STOCK COMPANY".
     Validate this in the company group so the company group gets the repair, not the
     whole document.
5. **Connection errors kill the whole content.** There is no retry on transport errors in
   `llm/client.py`. 2 of 4 contents died after one call. Add 3 retries with backoff for
   connection, 5xx and 429 errors, and lower the default `--jobs` for this gateway (2).

## Design agent: why it can't converge

- **It is anchored on the default design.** The prompt includes `reference_blank_design`, the full
  `default.html`. All 4 attempts on content f3c446 were the same 14-page, all-A4-portrait layout,
  close to the default. The orientation draw had no visible effect.
  - Remove the full reference. Give the slot-format rules (still unticked in todo:
    "Condensed slot-format rules") and at most a minimal 1-page example that has no styling.
- **The fill errors are too vague to fix.** "kpis: a flowing item cannot fit on one page" doesn't say
  which page role, region size, item height or font size is involved. Add these to the error text so the
  agent can act on it, e.g. "kpis item 3 is 180 mm tall in a 120 mm region on page role board".
- **The prompt contradicts the rules.** `configs/design.yaml` still carries workspace-agent
  text, and the model receives the whole file:
  - `reading_order` says "Every `data-gt-ro` must be updated", but the format says "No data-gt
    attributes";
  - "must_be_written_before_any_code";
  - "Do not copy the work folders".
  - Fix: rewrite these for a blank-design reply. Reading order goes through DOM order, `data-order`
    and region chains. Send only the criteria, randomness, distinctness and rules sections.
- **Repair conversations keep every earlier reply.** Each round resends all previous 10k-character HTML
  replies plus the contact image, so tokens grow every round (139k in for one content).
  - Fix: keep the system prompt, the original request, the last reply and the problems only.
- **The orientation choice isn't checked against the HTML.** `design_spec.orientation.pages` should match
  the `data-size` values actually used. Add that to `checks.py`.
- **`requested_model: gpt-6-luna` in `design.yaml` is unused.** Routing comes from
  `configs/models.yaml`, so the line is misleading. Either use it or remove it.
- **Image input is untested.** `llm/client.py` sends the contact sheet as an `image_url` part.
  Confirm that `gpt-5.6-luna` on this gateway accepts images. If it doesn't, the call fails or
  the image is ignored silently.

## Element agent

- **The group prompts are still large.** Every group gets `variables`, the full field
  listings, and statements get the whole catalogue. The phase 1 test used 12 calls for one content.
- **Key equality is too strict.** `if set(values)!=fields` rejects a reply that has an extra or
  missing key. That cost the phase 1 test its run. Accept extra keys (ignore them) and repair only
  the missing ones.
- **Dead code.** `PooledContentAgent.__init__` still builds the old single-call prompt (`extra`,
  `listing`, `self.messages[1]`), which `ElementAgent` never uses. Remove it so nobody tunes the wrong
  prompt.
- **Repair routing is fragile.** It matches field names inside the error text. `ContentError.problems` already
  has `field: message` entries, so route by that prefix.
- **The language-leak check misses the v1 case.** For a Vietnamese block it only fires when fewer than 10% of words
  are accented. An English word or clause inside a Vietnamese sentence ("prospectively") is
  not caught. Also flag Vietnamese blocks containing 2+ English stop words, or any word longer than 6 letters
  with no Vietnamese letters that isn't in a small allow-list (VND, EPS, …).

## Smaller issues

- `browser_checks(..., forbidden=())` never uses `forbidden`. The forbidden-words check lives in the agent
  instead. Fine, but remove the parameter.
- `design_check` reports the ledger entry as the literal string "ledger". Report its doc_id instead, so the
  agent knows which design it collided with. The ledger rows should store doc_id.
- `ledger.recent` reads the whole JSONL every call. Fine for now.
- `cli.py` and `elements.py` are written as dense one-liners (`a;b;c` chains, single-letter names).
  They are hard to review and to fix. Reformat them before more logic is added.
- `out/` mixes test outputs (`fake_design_check/`, `probe_defects/`, `size_checks/`,
  `export_check/`, `phase1/`) with the dataset. Move checks to `out/_checks/` or `.work/`.
- Fixture runs force `lang='vi'`, so English fill and render are never tested offline. Add an English
  fixture.

## What is fine

- Package layout, config split, `configs/doc_types/financial_report.yaml` with pool, elements and
  design sections; `content.yaml`; editable install.
- Pool split into `vi/` and `en/` with matching keys and placeholders; the leakage scan found no bad entries.
- The extra sizes in `SIZES`; the image-size check expects `round(px * dpi / 96)`.
- Language assignment (`choose_language`) and per-language stats; export balance gate.
- Fixture default-design path with 0 lint issues; 14 tests pass.

## Order to fix

1. Bugs 1–5.
2. Design prompt: remove the reference design, add condensed format rules, fix contradictions,
   trim repair history, make fill errors specific.
3. Element agent: lenient keys, routing by `ContentError.problems`, smaller prompts, remove dead code.
4. Re-run phase 5: `--n 2` first (1 vi + 1 en), then `--n 6`. Record calls, tokens and time per stage.

---

# Review 2: after FIX_PLAN steps 0–4 (2026-11-02, ~02:10)

Codex was still editing (`cli.py`, `agent.py`, `checks.py` changed at 02:04), so treat this as a snapshot.
Tests: **18 passed, 2 failed** (`test_layout` builds args without `batch`; `test_design_rejects_off_draw_and_copied_ledger`
no longer sees the ledger rejection). No live run yet.

The structure now matches the fix plan: one `DocumentAgent`, rebuilt short history, token caps, local JSON repair,
transport retries, typed `SourceContent`/`DesignSpec`/`RunRecord`, `check_tree`, batch design call.
The elements prompt is small (~3.5k tokens estimated for vi and en, cap 9k).

## Must fix before any live run

1. **Every live document will fail on the company name.** `DocumentAgent._validate_field` replaces
   `cover_company`/`auditor_firm` with `mixed_case(value)[0]`, which is the *mixed-case* form ("Công ty Cổ phần …").
   `fill_pool` then calls `mixed_case` again, and the case-sensitive `LEGAL` regex rejects it
   ("must start with CÔNG TY"). Verified:
   `mixed_case(mixed_case('CÔNG TY CỔ PHẦN BAO BÌ MINH LỘC')[0])` raises.
   Fix: validate with `mixed_case`, but keep the original upper-case value. Also make `LEGAL` case-insensitive.
2. **The JSON-repair call has no task in it.** When local repair fails, `elements()` sends only
   `[system, "Return valid JSON only. Parser error: …"]`, without the elements task or the broken reply. The model
   has nothing to fix and will invent an answer. Fix: resend the same elements messages (task, accepted
   summary) plus one line: "Your previous reply was not valid JSON (error at line X col Y). Reply again with the
   complete JSON." That costs about the same as the first call; the broken reply is not needed.
3. **Long problem lists make design repairs fail without a call.** `browser_checks` reports every overlapping
   pair (O(n²)) and every small-font child. A bad design can produce hundreds of lines. The repair prompt then
   exceeds the 16k cap, and `_call` raises before asking the model.
   Fix: dedupe, group by kind ("overlap: 34 pairs, e.g. …"), and keep at most 20 lines plus counts.
4. **The design-repair history resends the element task.** `history(phase="design")` always adds `self.elements_task`
   (~8.4k chars) and the accepted-elements summary, then the design task, the latest full design reply and the problems.
   That is ~13–14k estimated tokens before the problem list, close to the 16k cap (and it pays for 2.5k tokens that
   the design doesn't need). Fix: the design and design-repair history should be system + design task + latest design +
   problems. The inventory in the design task already describes the content.

## Should fix

5. **One reply for N designs.** `design_batch` asks for N full designs (each 4×10 options plus ~10–15k chars of HTML) in one
   reply. At `--batch 6` that is ~30k output tokens in a single JSON, the same shape that broke in v1. Cap
   designs per call at 3 (`--batch 6` = two design calls), or return the designs as N separate JSON objects
   separated by a marker so one bad design doesn't lose the others.
6. **Design work is serialized globally.** `batch_lock` is held for the whole design and repair phase of a batch,
   so with `--jobs 2` the second batch's designs wait for the first batch's renders and repairs. It is correct
   for the ledger, but slow. Hold the lock only while reading the ledger and appending to it.
7. **Final validation problems can bypass repair.** If `validate_content` on the merged document reports a field
   that isn't in `requested_ids` (for example `notes: …` from a pool/table merge), `_error_fields` returns `{}` and
   the error is raised with no repair. Map `notes` problems to `note_tables` / `note_charts`.
8. **Pool selection uses the design seed.** `DocumentAgent` is built with `design_seed(seed, 0)`, and the pool entry and
   chart notes are chosen from that. Use the spec seed, so content choice and design choice are independent.
9. **The text-contrast probe can be wrong.** It walks up to the first ancestor with a non-transparent background
   colour. Text on a background image or gradient is compared with that colour (or white). Skip the
   contrast check when an ancestor has `background-image`, and report it as "unchecked".
10. The two failing tests: update `test_layout` for `--batch`, and check whether the ledger-rejection test broke because
    `check()` now reads `row["design_spec"]` while the test passes bare specs.

## Fine

- `parse_json` local repair (balanced object, trailing commas, closing brackets) and transport retries
  (3 attempts, 429/5xx/connection).
- `json_mode: true` on the OpenAI endpoint. Still verify once that the gateway accepts it.
- Token estimate and caps logged per call (`estimated_tokens_in`, `call_kind`, `repair_number`).
- Failed bundles hold only spec/trace/problems/replies/design. `.tmp` is cleaned and `check_tree` runs.
- `cli.py` and `agent.py` are now readable.

## Review 2 status (fixed by Claude, 2026-11-02)

- [x] 1. Company name: `_validate_field` only validates and keeps the agent's upper-case name; `LEGAL` in
  `content/pool.py` is case-insensitive and allows any spacing inside legal forms.
- [x] 2. JSON retry: `DocumentAgent._json_retry` resends the same task messages plus one note
  ("previous reply was not valid JSON (…)"). This applies to elements, design and batch design. The broken reply is not resent.
- [x] 3. `design/checks.summarize_problems`: dedupes and groups by kind with counts and up to 3 examples, at most 20 lines.
  300 overlap lines become 1 line. Used in the design repair prompt.
- [x] 4. The design and design-repair history is system + design task + latest design + problems (no elements task).
- [x] 10. `test_layout` passes `batch=1`; the ledger test matches the new wording. The pytest cache moved to `.cache/pytest`,
  so the repo-root check passes. **20 passed.**
- Simulated check (FakeProvider): a truncated element reply triggers one retry that still carries the task; upper-case
  company name kept; ~3.5k estimated input tokens per call.
- Open: items 5–9 (batch size cap, global design lock, `notes` problem routing, pool seed, contrast on images).
