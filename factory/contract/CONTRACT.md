# Labeling Contract

Version: **0.2.0** (`core.contract.models.CONTRACT_VERSION`). Taxonomy: [`configs/taxonomy.yaml`](../../configs/taxonomy.yaml).

## 1. Purpose

The contract defines what the factory emits and what every downstream stage (bounding-box extraction, degradation, review UI, evaluation) may rely on. It covers:

- the document folder layout,
- `document.json`, DocIR (`content.json`), `spec.json`, and `trace.json`,
- the `data-*` attributes on each page's HTML,
- the rules the linter enforces.

The key words MUST, MUST NOT, and SHOULD are normative. Pydantic models in [`core/contract/models/`](models/) are the machine-readable form of sections 4–6; this document and those models must change together, with a version bump.

## 2. Document folder

```
out/documents/{doc_type}/{doc_id}/
  document.json      # DocumentManifest (section 5)
  content.json       # DocIR (section 4)
  pagination.json    # Pagination (section 5)
  spec.json          # the pipeline's spec (subclass of BaseSpec)
  trace.json         # Trace
  style.css          # document-wide styles (copy of what is inlined in pages)
  assets/            # fonts, images, seals, signatures, chart images
  pages/
    page_001.html
    ...
  images/
    page_001.png     # OCR input, rendered at document.json image_dpi
    ...
```

- `doc_id`: `{doc_type}_{NNNNNN}`, unique across documents, failures, and staging.
- Bundles are grouped under `documents/{doc_type}/`; failed bundles use the same
  type grouping under `failed/{doc_type}/`.
- `page_id`: `{doc_id}_p{NNN}` with a 1-based, zero-padded index.
- Page files: `pages/page_{NNN}.html`, one per entry in `document.json`.
- Every published document includes `images/page_{NNN}.png` at the fixed DPI in
  `document.json`; the image and HTML use the same page index.

## 3. Page HTML

### 3.1 Page requirements

- A page MUST render offline: no network requests. Fonts, images, and scripts are inlined or referenced relatively inside the document folder.
- A page MUST declare its size with `@page { size: W H; margin: 0 }` and a `<body>` of exactly that size in `mm`. A spread is one HTML page whose width covers both pages.
- A page MUST be fully rendered when `document.fonts.ready` resolves and `window.__FACTORY_READY__ === true` (set after KaTeX, charts, and images finish).
- Text MUST be UTF-8 and Unicode NFC.

### 3.2 Page attributes (on `<body>`)

| Attribute | Required | Value |
|---|---|---|
| `data-doc-id` | yes | Document ID |
| `data-page-id` | yes | Page ID |
| `data-page-index` | yes | 1-based index |
| `data-page-role` | yes | Pipeline-defined role (`cover`, `B01`, `kpi`, …) |
| `data-page-kind` | yes | `single` or `spread` |
| `data-page-doc-type` | yes | Taxonomy `page_attributes.doc_type` |
| `data-page-lang` | yes | Document/page language from `DocIR.lang` (`vi`, `en`, `en_vi_mixed`) |
| `data-page-layout` | yes | Taxonomy `page_attributes.layout` |
| `data-page-{attr}` | optional | Any other key in `page_attributes` |

### 3.3 Block attributes

A **block** is an element with `data-gt-cat` whose value is a block category (taxonomy `categories.text`, `non_text`, or `extension`).

| Attribute | Required | Value |
|---|---|---|
| `data-gt-id` | yes | DocIR block ID |
| `data-gt-cat` | yes | Block category |
| `data-gt-ro` | yes | Reading order within the page, integers `1..n` |
| `data-gt-part` | if split | `k/n` — this element is piece `k` of `n` of the block |
| `data-gt-lang` | text blocks | This block's language; it may differ from the document language |
| `data-gt-latex` | `equation_isolated` | LaTeX ground truth |
| `data-gt-parent` | optional | Block ID this block belongs to (caption → table/figure/chart) |
| `data-gt-attr-{key}` | optional | Any key in `block_attributes`, with `_` written as `-` (e.g. `data-gt-attr-frame-type`) |

### 3.4 Span attributes

A **span** is an element with `data-gt-cat` whose value is a span category. Spans MUST be descendants of a text-bearing block.

| Span category | Required attributes |
|---|---|
| `equation_inline` | `data-gt-latex` |
| `footnote_mark` | optional `data-gt-target` (footnote block ID) |

Plain text inside a block is implicitly `text_span`; it is not tagged.

### 3.5 Ignored content

`data-gt-ignore` marks visible content that is not ground truth (ornaments, background shapes, decorative numerals). Content inside an ignored element is excluded from all ground truth.

### 3.6 Structure rules

1. Blocks MUST NOT be nested inside other blocks. Captions, footnotes, and figures are sibling blocks linked by `data-gt-parent` or `data-gt-target`.
2. Tables MUST be real `<table>` elements on the block element itself, with consistent `rowspan`/`colspan`.
3. Rendered math (KaTeX output) MUST be inside the element carrying `data-gt-latex`.
4. Every visible, non-empty text node and every visible image MUST be inside a block or inside a `data-gt-ignore` element.

### 3.7 Ground-truth text extraction

The linter, DocIR check, and downstream stages extract a block's text with one algorithm:

1. Take the block's DOM subtree, in document order.
2. Drop subtrees marked `data-gt-ignore` and elements hidden by CSS (`display:none`, `visibility:hidden`).
3. Replace each `equation_inline` span with `$` + its `data-gt-latex` + `$`.
4. Concatenate text nodes; `<br>` and block-level element boundaries become `\n`; collapse runs of whitespace within a line to one space; trim.
5. Normalize to NFC.

For `table` blocks the ground truth is the minified table HTML (attributes other than `rowspan`/`colspan` removed). For `equation_isolated` it is `data-gt-latex`.

### 3.8 Reading order

Reading order is visual and follows the document's declared regions:

1. Header furniture, then regions in ascending `data-chain` order, then the
   footnote area, then footer furniture and page number.
2. Inside a multi-column region, read each column from top to bottom, then the
   next column. A paragraph crossing a column or page boundary is represented
   by consecutive pieces with the same `data-gt-id` and increasing
   `data-gt-part` values.
3. A spanning float divides a region into upper and lower bands. The upper
   band is read first, followed by the float and its caption, then the lower
   band. A template may instead declare a columns-under-float case; its
   `ro_cases` value records that order.
4. Captions follow the float they describe, in the printed order. A margin
   caption follows its float. Boxes and sidebars are read at their anchor.

`ro_level` (`L0`–`L4`) and `ro_cases` are recorded in `spec.json`,
`document.json`, and each page entry. These fields describe layout and are not
taxonomy attributes.

### 3.9 Example

```html
<body data-doc-id="newspaper_000142" data-page-id="newspaper_000142_p001" data-page-index="1"
      data-page-role="front_page" data-page-kind="single"
      data-page-doc-type="newspaper" data-page-lang="vi" data-page-layout="multi_column">
  <div class="ornament" data-gt-ignore></div>

  <h1 data-gt-id="b3" data-gt-cat="title" data-gt-ro="1" data-gt-lang="vi">Hà Nội khởi công tuyến metro số 5</h1>

  <p data-gt-id="b7" data-gt-cat="text_block" data-gt-ro="2" data-gt-lang="vi">
    Chi phí dự kiến là
    <span data-gt-cat="equation_inline" data-gt-latex="1{,}2 \times 10^{4}"><!-- KaTeX --></span> tỷ đồng
    <sup data-gt-cat="footnote_mark" data-gt-target="b20">1</sup>.
  </p>

  <table data-gt-id="b9" data-gt-cat="table" data-gt-ro="3" data-gt-part="1/2"
         data-gt-attr-frame-type="fewer_line">…</table>
  <p data-gt-id="b10" data-gt-cat="caption_table" data-gt-ro="4" data-gt-parent="b9">Bảng 1. …</p>
</body>
```

Extracted text of `b7`: `Chi phí dự kiến là $1{,}2 \times 10^{4}$ tỷ đồng 1.`

## 4. DocIR (`content.json`)

Model: `core.contract.models.DocIR`. DocIR is the semantic source of the document.

- `blocks` are in **document reading order**.
- Each block has `id`, `cat`, `content`, and optional `lang`, `attrs`, `parent`, `section`.
- `DocIR.lang` is the document-level language. Each text block's `lang` records
  the language of its own text and may differ in a mixed-language document.
- `content.kind` depends on the category:

| `content.kind` | Categories | Fields |
|---|---|---|
| `text` | text categories, `handwriting` | `spans`: list of `text`, `equation_inline`, `footnote_mark` |
| `table` | `table` | `html` (minified), `header_rows` |
| `equation` | `equation_isolated` | `latex` |
| `figure` | `figure` | `asset`, `description` |
| `chart` | `chart` | `chart_type`, `data` |
| `mark` | `seal`, `signature`, `form_field`, `checkbox`, `qr_code`, `barcode` | `asset`, `value` |

## 5. Pagination and `document.json`

- `pagination.json` (`core.contract.models.Pagination`): for each page, its role and the ordered list of block references. A `BlockRef` names a block and, if split, its `part`/`parts` and for tables the body `row_range`.
- `document.json` (`core.contract.models.DocumentManifest`): dataset, contract and taxonomy versions, provenance hashes, image DPI, doc ID and type, flow, page count, per-page `page_id`, `file`, `role`, `kind`, size in mm, and document attributes.

## 6. Spec and trace

- `spec.json`: the pipeline's spec, a subclass of `core.contract.models.BaseSpec` (doc ID, doc type, seed, flow, page-count range, language, requested attributes, brief). If the type config names a `language_variable`, the seeded value is recorded here as the document language.
- `trace.json` (`core.contract.models.Trace`): factory version, timing, status, and events (stage start/end, LLM and tool calls with provider, model, prompt ID, tokens, cost; checks; retries; errors).

## 7. Linter rules

Rules have stable IDs so reports and the review UI can reference them. `E` = error (document rejected), `W` = warning (recorded).

| ID | Level | Rule |
|---|---|---|
| C001 | E | Folder contains every file in section 2; every page in `document.json` exists |
| C002 | E | `<body>` page attributes present and match `document.json` |
| C003 | E | Page renders offline (no network requests) and becomes ready within the timeout |
| C004 | E | Categories and attribute values exist in the taxonomy version recorded in `document.json` |
| C005 | E | Every block has `data-gt-id`, `data-gt-cat`, `data-gt-ro`; `data-gt-id` exists in DocIR |
| C006 | E | On each page, `data-gt-ro` is a permutation of `1..n` |
| C007 | E | A `data-gt-id` appears once per page, and across pages only as pieces with `data-gt-part` `1/n..n/n` |
| C008 | E | No block nested in another block; spans only inside text-bearing blocks |
| C009 | E | `equation_isolated` and `equation_inline` carry `data-gt-latex` that KaTeX parses |
| C010 | E | `table` blocks are `<table>` elements with consistent row/column spans |
| C011 | E | Every visible text node and image is inside a block or `data-gt-ignore` |
| C012 | E | DocIR coverage: every DocIR block appears on some page; all pieces of a split block appear in order |
| C013 | E | DocIR text match: extracted text (3.7) of each block, pieces joined, equals DocIR text |
| C014 | E | Text is NFC |
| C015 | W | Content overflows the page or a block is clipped |
| C016 | W | A labeled block is fully covered by another element |
| C017 | W | `data-gt-parent` / `data-gt-target` points to a block on no page |

## 8. Versioning

- Contract and taxonomy versions use semantic versioning and are recorded in every `document.json`. The dataset release version is in `out/VERSION` and is copied into each manifest.
- Adding optional attributes or categories is a minor change; renaming, removing, or changing a rule's meaning is a major change.
- Documents are never silently migrated; a migration script produces new documents with the new version.

## 9. Provisional

Until contract v0.2, the first runnable slice uses these conventions:

- The paginator creates header, footer and page-number blocks per page and appends
  them to DocIR with `section="page_furniture"`, using IDs such as
  `pf_p003_header`. Their page reading order lives in Pagination. The semantic
  document order comparison excludes these appended furniture blocks.
- Each split table piece is a complete `<table>` containing the original header
  rows followed by its body-row slice. C013 compares the header once (and verifies
  each repeated header is identical), followed by all body rows in order.
  `BlockRef.row_range` indexes body rows, excluding repeated header rows.
- A document may contain an `extra/` directory for pipeline-owned sidecar files.
