# GT Review app: plan

A local web app for checking the factory's ground truth by eye, block by block,
and recording a decision for each page and document. Design sketch:
`design/review-ui.fig` (screens `01 · Queue`, `02 · Page review`), previews in
`design/*.png`.

## 1. Goals and limits

- Reviewers check the factory's labels (block boxes, categories, reading order,
  ground-truth text, attributes) against the rendered page image and record a
  verdict.
- The app **never edits a document bundle**. Every decision and correction is
  written to a separate review file. The factory and export read that file;
  bundles stay reproducible from their seed.
- It runs locally, against any `out/<run>/<subset>/` folder, for 1–3 reviewers.
  No accounts beyond a reviewer name, no cloud.
- Contract 0.2.0 and taxonomy 0.1.0 are the source of truth. The app reads the
  taxonomy from the bundle's recorded version and refuses bundles with versions
  it does not know.

## 2. What the factory already gives us, and the one gap

Each bundle in `documents/{doc_type}/{doc_id}/` has `document.json`,
`content.json` (DocIR), `pagination.json`, `pages/page_NNN.html`,
`images/page_NNN.png` (200 dpi) and `trace.json`. `index/documents.jsonl` lists
the bundles.

**Gap: block boxes are not stored.** They are computed only at export time
(`factory/runner/export.py`, `capture()`), by measuring `[data-gt-id]` elements
in Playwright. The app needs them for every page, so the factory should write
them once:

- New sidecar `extra/boxes.json`, written at the end of `generate` (and by a
  `factory boxes <path>` backfill command for existing runs). Per page: the
  image size in px, and for each block element `id`, `cat`, `ro`, `part`,
  `poly` (8 numbers, image px at the document DPI), `lang`, `parent`, `attrs`,
  and the extracted ground-truth text (contract 3.7) or table HTML.
  Ignored regions (`data-gt-ignore`) are listed separately.
- It reuses the capture JavaScript from `export.py`; move that into one shared
  function so export and boxes cannot drift.
- Lint results are also only printed today. `factory lint` should write
  `extra/lint.json` (`rule_id`, level, page, message, and block id where the
  rule knows it) so the app can show them per page and per block.

Contract change: `extra/` is already pipeline-owned (section 9), so this is a
minor, additive change. Document the two files in CONTRACT.md.

## 3. Architecture

```
app/
  server/            Python, FastAPI. Imports factory.contract models directly.
    main.py          routes
    bundles.py       scan a run folder, load bundles, serve images and pages
    reviews.py       read/write review files, merge state
    schema.py        pydantic models for reviews (section 5)
  web/               React + TypeScript + Vite
    src/routes/      Queue, PageReview
    src/canvas/      page image, box overlay, reading-order path, box editing
    src/inspector/   block details, verdicts, block list
    src/api.ts       typed client (generated from the FastAPI OpenAPI schema)
  design/            sketch and previews
```

Why this stack: the server must read the factory's pydantic models and reuse
its text extraction, so it is Python. The UI is a canvas-heavy single page with
keyboard control, so a React SPA is simpler than server-rendered pages. SVG over
an `<img>` is enough for boxes; no canvas library.

Run: `app/run.ps1 <run folder>` starts the server on `127.0.0.1:8765` and
serves the built web app. In development, Vite proxies `/api` to the server.

## 4. API

| Route | Returns |
|---|---|
| `GET /api/runs` | run folders under `out/` |
| `GET /api/docs?run=&type=&status=&lang=&layout=&lint=&reviewer=&sort=` | queue rows with progress and top lint finding |
| `GET /api/docs/{doc_id}` | manifest, pagination, page roles, review state |
| `GET /api/docs/{doc_id}/pages/{n}` | boxes, lint findings, block ground truth, review state for the page |
| `GET /api/docs/{doc_id}/pages/{n}/image` | the PNG |
| `GET /api/docs/{doc_id}/pages/{n}/html` | the page HTML, sandboxed (for the HTML view) |
| `PUT /api/docs/{doc_id}/pages/{n}/blocks/{block_id}` | set a block verdict or correction |
| `PUT /api/docs/{doc_id}/pages/{n}/decision` | approve, flag or reject the page |
| `PUT /api/docs/{doc_id}/order/{n}` | corrected reading order for a page |
| `GET /api/stats?run=` | batch totals for the queue header |
| `GET /api/export?run=` | the merged review file, and the list of approved docs |

Writes are idempotent (`PUT` the full value) and carry the version the client
last read, so two reviewers on the same page get a conflict instead of a silent
overwrite.

## 5. Review data

One file per document: `out/<run>/<subset>/reviews/{doc_id}.json`, outside the
bundle. Versioned like the contract.

```jsonc
{
  "review_version": "0.1.0",
  "doc_id": "financial_report_000142",
  "bundle_hash": "…",            // from document.json provenance; stale if it changes
  "status": "in_review",          // todo | in_review | approved | flagged | rejected
  "pages": {
    "3": {
      "decision": null,           // approved | flagged | rejected, with reviewer and time
      "blocks": {
        "b17": {
          "verdict": "correct",   // correct | box_off | text_wrong | wrong_category | wrong_order | should_ignore
          "fix": null,            // optional correction, see below
          "note": "",
          "by": "linh.t", "at": "2026-11-05T16:02:11Z"
        }
      },
      "order": null               // corrected list of block ids, if changed
    }
  },
  "history": []                   // append-only log of every change
}
```

Corrections (`fix`) record what the reviewer believes is right: a new `poly`, a
new `cat`, an attribute value, or corrected text. They are **proposals**: export
applies only box, category, attribute and order fixes; a text fix always marks
the document `flagged` and goes back to the factory, because the HTML, DocIR and
image must agree (C013).

Document status is derived: `approved` when every page is approved; `rejected`
if any page is rejected; `flagged` if any page or text fix is flagged; otherwise
`in_review` once anything is recorded.

## 6. Screens

**01 · Queue.** Totals (approved, waiting, flagged, rejected with rule ids);
filters by doc type, status, language, layout, lint result, reviewer; table of
documents with per-page progress. "Start reviewing" opens the first unfinished
document by the current sort (lint issues first by default).

**02 · Page review.**
- Page rail: thumbnails with status and page role.
- Canvas: the page image with boxes colored by category, reading-order badges
  and path, lint markers on the blocks they name. Views: Image, HTML,
  side-by-side. Toggles: boxes, order, ignored regions. Zoom and pan.
- Inspector tabs:
  - Block: id, category, order, part, language, attributes, parent; ground-truth
    text or table HTML (rendered table and raw toggle); the C013 result; the six
    verdict buttons.
  - Page: page attributes, role, page decision, note.
  - Lint: every finding for the page, click to select its block.
  - Document: manifest, spec brief, trace summary (cost, retries).
- Reading-order list: drag to reorder; the path on the canvas follows.
- Keyboard: `Tab`/`Shift+Tab` block, `1`–`6` verdict, `J`/`K` page, `A`/`F`/`R`
  page decision, `B`/`O`/`I` toggles, `Shift+drag` redraw a box, `/` search.

Later screens, drawn after the first two work: **Lint failures** (all findings
across the run, grouped by rule, for triage) and **Export** (approved counts,
what corrections export will apply, write the review manifest).

## 7. Factory integration

- `factory export` reads `reviews/` and by default includes only approved
  documents, applying box, category, attribute and order fixes to the exported
  annotations. A flag `--include-unreviewed` keeps today's behaviour.
- `factory reviews report <run>` prints counts per verdict and per category, so
  repeated errors (for example captions often marked `wrong_order`) feed back
  into the design agent's checks.
- Flagged documents can be regenerated from their seed; the new bundle has a new
  `bundle_hash`, so the old review shows as stale and the document returns to
  the queue.

## 8. Decisions taken in this plan (change them before phase 2)

1. **Verdicts first, corrections second.** Phase 2 ships verdicts and page
   decisions only. Box, category, attribute and order corrections come in
   phase 3. Text is never corrected in the app.
2. **Pages are approved one at a time**; a document is approved when all its
   pages are.
3. **Reviews live beside the run** (`reviews/`), not in the bundle and not in a
   database. Plain JSON is diffable and easy for export to read. Revisit if more
   than ~3 reviewers work at once.

## 9. Risks

- Box drift: `boxes.json` must be measured with the same browser, fonts and
  DPI as the PNG. Store the image size with the boxes and refuse to draw when it
  does not match the PNG.
- Split blocks (`data-gt-part`) appear on several pages; the verdict is per page
  piece, and the inspector shows the other pieces.
- Spreads (`data-page-kind="spread"`) are wider images; the canvas must fit by
  width as well as height.
- Large tables make long ground-truth HTML; render it as a table with a raw
  toggle rather than one line of markup.
