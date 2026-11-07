# Prompt for Codex: build the GT Review app

You are implementing a local review app for the OCR ground-truth factory. Work in two folders:

- `OCR_VLM_benchmark_factory/`: the existing factory (Python package `factory`). Read `factory/contract/CONTRACT.md` and `configs/taxonomy.yaml` before anything else. They define every field the app shows.
- `app/`: the new app. It currently holds only the spec and the design.

## Read first

1. `app/PLAN.md`: the spec. Section numbers below refer to it.
2. `app/TODO.md`: the checklist. Work through it in order, tick items, and write each **Check** result under it. Use the same format as `.doc_local/academic_papers/TODO_v2.md`: say what you ran, what happened, and the numbers.
3. The design:
   - `app/design/01-queue.png` and `app/design/02-page-review.png` are the screens to build.
   - `app/design/sketch/ui.py` holds the exact colors (`C`, `CAT`), sizes and spacing; `screen_queue.py` and `screen_review.py` hold the layouts. Treat them as the visual spec.
   - The previews show a serif font only because of the preview tool. Use Inter for UI text and JetBrains Mono for ids, codes and numbers.
4. `factory/runner/export.py`: `capture()` and `CAPTURE` are the box measurement to reuse in phase 1.

## How to work

- Run all five phases in `TODO.md`, in order, without pausing for approval. Do not stop at a phase boundary to report.
- When a check fails, fix the cause and rerun the check until it passes. Then record what failed, what you changed and the passing result under the check, and carry on.
- Stop only for a real blocker: something you cannot fix without breaking a rule below, or that needs a decision only I can make (for example, changing the contract in a way that is not additive). Then write the blocker under the check, skip only the work that depends on it, and finish everything else.
- Problems in the factory that you find but that are not the app's job (for example, existing C013 mismatches between stored content and extraction) are recorded, not fixed. Do not let them block the app.
- Never edit files inside a document bundle (`out/**/documents/**`) except the new `extra/boxes.json` and `extra/lint.json` from phase 1. Review data goes in `reviews/` only [1, 5].
- Do not change what `factory export` produces until phase 5. After the phase 1 refactor, export output must be byte-identical on the same input; prove it with a diff.
- `doc_id` is not unique across subsets of a run (the test run reuses `academic_paper_000001` in all four). Key documents and reviews by subset and `doc_id` everywhere: API routes, review files and the queue.
- On Windows, every text read and write states `encoding="utf-8"`, in the app, in check scripts, and in any factory code you touch.
- Keep factory changes inside the factory's existing style: pydantic models in `factory/contract/models/`, CLI subcommands in `factory/cli.py`, tests in `tests/`. Bump the contract minor version and update CONTRACT.md for the two new sidecar files.
- Test data: `OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3/`. Do not regenerate it; backfill it.

## Stack (do not substitute)

- Server: Python 3.11+, FastAPI, uvicorn, in `app/server/`. Import `factory.contract` models and `factory.contract.extract` directly; do not copy them.
- Web: Vite + React + TypeScript in `app/web/`. Plain CSS modules or CSS variables taken from the design tokens; no UI kit. Draw boxes as SVG over an `<img>`; no canvas library.
- API types: generate the TypeScript client from FastAPI's OpenAPI schema. Do not hand-write duplicate types.
- `app/run.ps1 <run folder>` builds the web app if needed and serves everything on `127.0.0.1:8765`.

## What must be true when you are done

- Opening any page of the test run shows the PNG with every block's box in the right place, colored by category, numbered by `data-gt-ro`, with the reading-order path.
- Split blocks (`data-gt-part`) and spreads display correctly.
- If the box file's image size differs from the PNG, the app shows an error and draws no boxes.
- A reviewer can go through a whole document using only the keyboard shortcuts in PLAN.md section 6 and the design's status bar.
- Verdicts and page decisions survive a server restart; two browser tabs editing the same page get a conflict message, not a silent overwrite.
- The queue's totals and per-document page progress match the review files.
- Box, category and reading-order corrections survive a reload, and `factory export` applies them to approved documents only.

When all five phases are done, write a short report at the end of `TODO.md` covering:
- what was built
- every check result
- known gaps
- anything in the design you could not match, with the reason

## Out of scope

Accounts or auth beyond a reviewer name, cloud hosting, a database, editing ground-truth text in the app. For the Lint failures and Export screens, base the layout on the existing two screens; you do not need a design file first.
