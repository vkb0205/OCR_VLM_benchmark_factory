"""Build the OmniDocBench-style benchmark folder from the factory bundles.

Usage (from benchmark_factory/):
  .venv/bin/python .doc_local/benchmark_build/build.py [--limit N] [--root PATH]

Reads   <root>/bundles/<doc_type>/<doc_id>/       (factory bundles, lint-clean)
        <root>/source_content_src/ is not used; raw content is copied from
        benchmark_factory/.work/content/<doc_type>/out/seed_<seed>.json
Writes  <root>/{dataset.json, images/, pdfs/, mds/, configs/, metadata/, source_content/,
        README.md, VERSION, checksums.sha256}
Rebuilding replaces these generated items; bundles/ and metadata/MOVED_FROM.txt are never touched.
"""
import argparse, asyncio, csv, hashlib, io, json, re, shutil, sys, unicodedata
from collections import Counter
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FACTORY))
from PIL import Image
from factory.browser.browser import Browser
from factory.contract.extract import parse_html, table_html
from factory.contract.lint import lint_document
from factory.contract.taxonomy import Taxonomy
MAP = dict(title='title', section_header='title', text_block='text_block', list_item='text_block', reference='reference', header='header', footer='footer', page_number='page_number', caption_table='table_caption', caption_figure='figure_caption', caption_chart='figure_caption', caption_equation='equation_caption', table='table', figure='figure', chart='figure', equation_isolated='equation_isolated', code_block='code_txt', seal='figure', signature='figure', qr_code='figure', barcode='figure', form_field='abandon', checkbox='abandon', handwriting='text_block', footnote='page_footnote')


async def capture(browser, path):
    """Capture labelled block geometry, a PNG, and a PDF from one rendered page."""
    async with browser.page(path, device_scale_factor=200 / 96) as (page, blocked, failed):
        if blocked or failed:
            raise ValueError(f"Failed resources: {blocked + failed}")
        boxes = await page.evaluate('''() => {
          const b=document.body.getBoundingClientRect(), s=200/96;
          const poly=r=>[r.left-b.left,r.top-b.top,r.right-b.left,r.top-b.top,r.right-b.left,r.bottom-b.top,r.left-b.left,r.bottom-b.top].map(v=>Math.round(v*s*100)/100);
          return [...document.querySelectorAll('[data-gt-id]')].map(e=>{
            const spans=[], w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
            while(w.nextNode()){const n=w.currentNode;if(!n.textContent.trim())continue;
              const r=document.createRange();r.selectNodeContents(n);
              for(const box of r.getClientRects())spans.push({category_type:'text_span',poly:poly(box),ignore:false,text:n.textContent});}
            return {id:e.dataset.gtId,category:e.dataset.gtCat,order:Number(e.dataset.gtRo),part:e.dataset.gtPart,
              poly:poly(e.getBoundingClientRect()),text:e.innerText,html:e.querySelector('table')?.outerHTML || (e.tagName==='TABLE'?e.outerHTML:null),spans};});
        }''')
        image = await page.screenshot(clip=await page.locator('body').bounding_box(), animations='disabled')
        pdf = await page.pdf(prefer_css_page_size=True, print_background=True)
        return boxes, image, pdf

VERSION = '0.1.0'
DPI = 200
JOBS = 4
DATA_SOURCE = {'academic_paper': 'academic_literature', 'financial_report': 'research_report'}
BACKGROUND = {'single_color': 'single_colored', 'multi_color': 'multi_colored', 'image': 'multi_colored'}
NO_MD = {'abandon', 'header', 'footer', 'page_number'}
GENERATED = ['dataset.json', 'images', 'pdfs', 'mds', 'configs', 'source_content', 'README.md', 'VERSION',
             'checksums.sha256', 'metadata/languages.json', 'metadata/documents.csv', 'metadata/pages.csv', 'metadata/stats.json']

CAPTURE = '''(textCats) => {
  const text = new Set(textCats), b = document.body.getBoundingClientRect(), s = 200 / 96;
  const R = v => Math.round(v * s * 100) / 100;
  const poly = r => [r.left-b.left, r.top-b.top, r.right-b.left, r.top-b.top, r.right-b.left, r.bottom-b.top, r.left-b.left, r.bottom-b.top].map(R);
  const nonwhite = c => { const m = (c || '').match(/[\\d.]+/g) || []; const [r, g, bl, a = 1] = m.map(Number); return a > 0.05 && !(r > 244 && g > 244 && bl > 244); };
  return [...document.querySelectorAll('[data-gt-id]')].map(e => {
    const cat = e.dataset.gtCat;
    const out = {id: e.dataset.gtId, category: cat, order: Number(e.dataset.gtRo), part: e.dataset.gtPart || null,
                 poly: poly(e.getBoundingClientRect()), text: e.innerText};
    if (cat === 'table') {
      const t = e.tagName === 'TABLE' ? e : e.querySelector('table');
      out.html = t.outerHTML;
      out.shaded = [...t.querySelectorAll('th,td')].some(c => nonwhite(getComputedStyle(c).backgroundColor));
    } else if (text.has(cat)) {
      const items = [], skip = n => n.parentElement.closest('[data-gt-ignore],[data-gt-cat="equation_inline"]');
      const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) {
        const n = w.currentNode, t = n.textContent;
        if (!t.trim() || skip(n)) continue;
        const re = /\\S+/g; let m, cur = null;
        while ((m = re.exec(t))) {
          const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
          const q = r.getClientRects()[0]; if (!q) continue;
          if (cur && Math.abs(q.top - cur.top) < q.height * 0.5 && q.left >= cur.left - 1) {
            cur.right = Math.max(cur.right, q.right); cur.bottom = Math.max(cur.bottom, q.bottom); cur.top = Math.min(cur.top, q.top);
            cur.text += t.slice(cur.end, m.index) + m[0]; cur.end = m.index + m[0].length;
          } else { if (cur) items.push(cur); cur = {top: q.top, bottom: q.bottom, left: q.left, right: q.right, text: m[0], end: m.index + m[0].length}; }
        }
        if (cur) items.push(cur);
      }
      const spans = items.map(i => ({top: i.top, left: i.left, category_type: 'text_span', ignore: false, text: i.text,
        poly: poly({left: i.left, top: i.top, right: i.right, bottom: i.bottom})}));
      for (const q of e.querySelectorAll('[data-gt-cat="equation_inline"]')) {
        const r = q.getBoundingClientRect();
        spans.push({top: r.top, left: r.left, category_type: 'equation_inline', ignore: false, latex: q.dataset.gtLatex, poly: poly(r)});
      }
      spans.sort((a, b2) => Math.round(a.top / 3) - Math.round(b2.top / 3) || a.left - b2.left);
      out.spans = spans.map(({top, left, ...rest}) => rest);
    }
    return out;
  });
}'''


def nfc(text):
    return re.sub(r'[ \t]+', ' ', unicodedata.normalize('NFC', text)).strip()


def page_layout(dets, W, H):
    """single_column / double_column / three_column / 1andmore_column from block positions."""
    cands = []
    for d in dets:
        x0, y0, x1, y1 = d['poly'][0], d['poly'][1], d['poly'][4], d['poly'][5]
        if d['category_type'] == 'text_block' and y1 - y0 >= 0.06 * H and x1 - x0 >= 0.18 * W:
            cands.append((x0, y0, x1, y1))
    best = 1
    for a in cands:
        group = []
        for b in cands:
            overlap = min(a[3], b[3]) - max(a[1], b[1])
            if overlap >= 0.5 * min(a[3] - a[1], b[3] - b[1]):
                group.append(b)
        group.sort()
        count, edge = 0, -1e9
        for g in group:
            if g[0] >= edge - 0.01 * W:
                count += 1; edge = g[2]
        best = max(best, count)
    if best == 1:
        return 'single_column'
    if any(c[2] - c[0] >= 0.7 * W for c in cands):
        return '1andmore_column'
    return 'double_column' if best == 2 else 'three_column'


def is_colorful(image):
    px = list(image.resize((48, 64)).getdata())
    return sum(1 for p in px if min(p) < 225) / len(px) > 0.6


async def process(browser, taxonomy, folder, staging, gate, source_content):
    async with gate:
        manifest = json.loads((folder / 'document.json').read_text())
        doc_id = manifest['doc_id']
        issues = await lint_document(folder, browser, taxonomy)
        if issues:
            return None, [f'{doc_id}: lint {issues[0].rule_id} {issues[0].message}']
        content = {b['id']: b for b in json.loads((folder / 'content.json').read_text())['blocks']}
        spec = json.loads((folder / 'spec.json').read_text())
        lang = spec.get('lang', 'vi')
        pages, problems = [], []
        for p in manifest['pages']:
            async with browser.page(folder / p['file'], device_scale_factor=DPI / 96) as (page, blocked, failed):
                if blocked or failed:
                    return None, [f'{doc_id}: resources failed {blocked + failed}']
                boxes = await page.evaluate(CAPTURE, sorted(taxonomy.text))
                png = await page.screenshot(clip=await page.locator('body').bounding_box(), animations='disabled')
                pdf = await page.pdf(prefer_css_page_size=True, print_background=True)
            image_id = f"{doc_id}_p{p['index']:03}"
            im = Image.open(io.BytesIO(png)).convert('RGB')
            W, H = im.size
            im.save(staging / 'images' / f'{image_id}.jpg', quality=95)
            (staging / 'pdfs' / f'{image_id}.pdf').write_bytes(pdf)
            dets, md, ids, relations = [], [], {}, []
            for i, b in enumerate(sorted(boxes, key=lambda b: b['order']), 1):
                src = content[b['id']]
                if b['category'] not in MAP:
                    problems.append(f'{image_id}: unmapped category {b["category"]}'); continue
                cat = MAP[b['category']]
                if b['category'] == 'footnote' and src.get('parent'):
                    cat = 'table_footnote' if content[src['parent']]['cat'] == 'table' else 'figure_footnote'
                c = src['content']
                split = bool(b['part']) and not b['part'].endswith('/1') or bool(b['part']) and not b['part'].startswith('1/')
                full = ''.join('$' + s.get('latex', '') + '$' if s['type'] == 'equation_inline' else s.get('text', '')
                               for s in c.get('spans', []))
                text = nfc(b['text'] if (split or not full) else full)
                d = dict(category_type=cat, poly=[min(max(v, 0), W if j % 2 == 0 else H) for j, v in enumerate(b['poly'])],
                         ignore=False, order=i, anno_id=i, attribute={},
                         factory=dict(block_id=b['id'], category=b['category'], part=b['part']))
                if any(abs(v - w) > 3 for v, w in zip(b['poly'], d['poly'])):
                    problems.append(f'{image_id}: {b["id"]} outside the page by more than 3 px')
                if cat == 'table':
                    html = table_html(parse_html(b['html']))
                    d['html'] = html
                    d['attribute'] = {'table_layout': 'vertical', 'with_span': bool(re.search(r'(row|col)span', html)),
                                      'line': src['attrs'].get('frame_type', 'full_line'), 'language': f'table_{lang}',
                                      'include_equation': False, 'include_backgroud': bool(b.get('shaded')),
                                      'table_vertical': False}
                elif cat == 'equation_isolated':
                    d['latex'] = c.get('latex', text)
                elif cat in ('figure',):
                    d['text'] = ''
                else:
                    d['text'] = text
                if 'spans' in b:
                    d['line_with_spans'] = b['spans']
                if cat in ('text_block', 'title', 'reference'):
                    d['attribute'] = {'text_language': f"text_{src.get('lang') or lang}",
                                      'text_background': BACKGROUND.get(src['attrs'].get('text_background'), 'white'),
                                      'text_rotate': 'normal'}
                dets.append(d)
                if b['id'] in ids:
                    relations.append(dict(source_anno_id=ids[b['id']], target_anno_id=i, relation='truncated', relation_type='truncated'))
                ids[b['id']] = i
                if cat not in NO_MD:
                    md.append(d['html'] if cat == 'table' else '$$' + d['latex'] + '$$' if cat == 'equation_isolated'
                              else '```\n' + text + '\n```' if cat == 'code_txt' else '![]()' if cat == 'figure'
                              else '# ' + text if cat == 'title' else text)
            for d in dets:
                parent = content[d['factory']['block_id']].get('parent')
                if parent in ids and ids[parent] != d['anno_id']:
                    relations.append(dict(source_anno_id=ids[parent], target_anno_id=d['anno_id'], relation='parent_son', relation_type='parent_son'))
            layout = page_layout(dets, W, H)
            pages.append(dict(layout_dets=dets, page_info=dict(
                page_no=p['index'] - 1, height=H, width=W, image_path=f'{image_id}.jpg',
                page_attribute=dict(data_source=DATA_SOURCE.get(manifest['doc_type'], manifest['doc_type']), language=lang,
                                    layout=layout, watermark=False, fuzzy_scan=False, colorful_backgroud=is_colorful(im)),
                factory=dict(doc_id=doc_id, doc_type=manifest['doc_type'], page_role=p['role'], dpi=DPI)),
                extra=dict(relation=relations)))
            (staging / 'mds' / f'{image_id}.md').write_text('\n\n'.join(md) + '\n', encoding='utf-8')
        meta = dict(doc_id=doc_id, doc_type=manifest['doc_type'], seed=spec['seed'], pages=len(pages),
                    **{k: spec['variables'].get(k) for k in ('industry', 'company_size', 'fiscal_year')},
                    company=source_content.get('cover_company', ''), theme=manifest['composition'].get('theme'),
                    cover=manifest['composition'].get('cover'), variants=json.dumps(manifest['composition'].get('variants'), ensure_ascii=False),
                    content_source='factory element agent', factory_version=manifest.get('provenance',{}).get('factory_version','2'))
        return (pages, meta), problems


def check(root, pages, taxonomy_cats):
    problems, orders = [], 0
    for page in pages:
        info = page['page_info']
        im = Image.open(root / 'images' / info['image_path'])
        if im.size != (info['width'], info['height']):
            problems.append(f"{info['image_path']}: image size {im.size} differs from page_info")
        if not (root / 'mds' / info['image_path'].replace('.jpg', '.md')).exists():
            problems.append(f"{info['image_path']}: no markdown")
        if not (root / 'pdfs' / info['image_path'].replace('.jpg', '.pdf')).exists():
            problems.append(f"{info['image_path']}: no pdf")
        dets = page['layout_dets']
        if [d['order'] for d in dets] != list(range(1, len(dets) + 1)):
            problems.append(f"{info['image_path']}: order is not 1..n")
        anno = {d['anno_id'] for d in dets}
        for r in page['extra']['relation']:
            if r['source_anno_id'] not in anno or r['target_anno_id'] not in anno:
                problems.append(f"{info['image_path']}: relation points to a missing block")
        for d in dets:
            if d['category_type'] not in taxonomy_cats:
                problems.append(f"{info['image_path']}: category {d['category_type']} not in the OmniDocBench list")
            x = d['poly']
            if not (0 <= min(x[0::2]) and max(x[0::2]) <= info['width'] and 0 <= min(x[1::2]) and max(x[1::2]) <= info['height']):
                problems.append(f"{info['image_path']}: poly outside image ({d['category_type']})")
            if x[0] >= x[4] or x[1] >= x[5]:
                problems.append(f"{info['image_path']}: empty poly ({d['category_type']} order {d['order']})")
        orders += 1
    return problems


def readme(pages, docs, counts):
    cats = '\n'.join(f'| `{k}` | {v} |' for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    layouts = Counter(p['page_info']['page_attribute']['layout'] for p in pages)
    types = Counter(d['doc_type'] for d in docs)
    return f'''# Vietnamese synthetic document benchmark

Version {VERSION}. {len(docs)} documents, {len(pages)} pages ({', '.join(f'{v} {k}' for k, v in types.items())}).
All companies, people, addresses and figures are fictional.

The core of this folder follows the OmniDocBench layout: one annotation file, page images and PDFs, and
Markdown ground truth per page. The rest keeps the data traceable to the generator.

## Folder

| Path | What it is |
|---|---|
| `dataset.json` | Annotations for every page, in the OmniDocBench JSON format (`layout_dets`, `page_info`, `extra`) |
| `images/<doc_id>_pNNN.jpg` | Page images, 200 DPI. This is the OCR input |
| `pdfs/<doc_id>_pNNN.pdf` | One-page PDFs with a text layer, made from the same page |
| `mds/<doc_id>_pNNN.md` | Ground-truth Markdown per page, for text, formula, table and reading-order scoring |
| `configs/end2end.yaml` | OmniDocBench end-to-end config pointing at this folder |
| `metadata/documents.csv` | One row per document: id, seed, company, industry, size, year, pages, theme, cover, layouts |
| `metadata/pages.csv` | One row per page: image, document, role, layout, block count |
| `metadata/stats.json` | Counts by source, layout and category |
| `metadata/MOVED_FROM.txt` | Where the documents were moved from |
| `source_content/<doc_type>/<doc_id>.json` | The content the model wrote for each document (variables and values) |
| `bundles/<doc_type>/<doc_id>/` | The full factory bundle: labelled HTML pages, `content.json`, `pagination.json`, `spec.json`, `trace.json`, assets |
| `checksums.sha256` | SHA-256 of every file |

Page images are named `<doc_id>_p<NNN>`; `page_info.image_path` and `page_info.factory.doc_id` link a page to its document.

## Annotations

Follows OmniDocBench: `poly` holds the four corners clockwise from top left in image pixels, `order` is the reading
order (1..n), `anno_id` is unique per page, `text`/`html`/`latex` hold the ground truth, `line_with_spans`
holds one box per printed line, and `extra.relation` links captions to tables and figures (`parent_son`) and pieces of
one block on a page (`truncated`). Each relation carries its type under both `relation` and `relation_type`,
because the OmniDocBench README uses both spellings.

Additions: each layout det has a `factory` object (our own block ID, category and `part`), and each page has
`page_info.factory` (document, type, page role, DPI). OmniDocBench tools ignore unknown keys.
Language values are `vi`, `text_vi` and `table_vi`, which OmniDocBench does not have (it has English and Chinese).

How the page attributes are set:
- `layout`: from block positions. Two or three multi-line text blocks side by side give `double_column` or
  `three_column`; with a full-width block as well, `1andmore_column`. Tables and figures are not counted.
- `colorful_backgroud` (sic): true when more than 60% of the page is not near white.
- Table `line` is the drawn frame (`full_line`, `less_line`, `fewer_line`, `wireless_line`). `with_span` is true when
  the table has rowspan or colspan. `include_backgroud` (sic) is true when any cell is shaded.
  `table_layout` is `vertical` for all tables, because no text is rotated; its exact meaning in OmniDocBench is unverified.
- Not applicable here and set to false: `watermark`, `fuzzy_scan`, `table_vertical`, `include_equation`.

Category mapping from the factory's labels: `section_header` and `title` become `title`; `list_item` becomes `text_block`;
`chart`, `seal` and `signature` become `figure` (the original is in `factory.category`); captions become
`table_caption` / `figure_caption`; `footnote` becomes `page_footnote`, `table_footnote` or `figure_footnote`.

## Content in this version

| Category | Blocks |
|---|---|
{cats}

Layouts: {', '.join(f'{k} {v}' for k, v in sorted(layouts.items()))}.

The financial reports are Vietnamese audited statements (TT200): cover, auditor's report, board report, balance
sheet, income statement, cash-flow statement, notes and signatures, in 10 industries and 24 visual themes.
Content was written by Codex `gpt-5.6-luna`, one document at a time, then checked by the factory's number rules
(totals, balance, cash ties) and an originality check, and laid out and labelled by code. The labels come from the
rendered page, not from the model.

## Evaluate

```sh
python pdf_validation.py --config configs/end2end.yaml   # run inside an OmniDocBench checkout, paths adjusted
```

Predictions are one Markdown file per page, named like the image with `.md` instead of `.jpg`.
`configs/end2end.yaml` points `prediction.data_path` at `mds/` (the ground truth), which is only a self-test.

## Status and limits

- The OmniDocBench evaluator has not been run on this folder yet. Format checks done by the builder: every image
  size matches `page_info`, every `poly` is inside its image, `order` runs 1..n, every relation points to a block on
  the page, and every category is an OmniDocBench one.
- Many financial-report pages are tables and text only; there are few formulas, and no inline math. Reading order is
  mostly top to bottom. Harder multi-column layouts come with the academic-paper type.
- No dataset licence has been chosen. Do not redistribute until one is.
'''


def end2end():
    return '''end2end_eval:
  metrics:
    text_block:
      metric:
        - Edit_dist
        - BLEU
        - METEOR
    display_formula:
      metric:
        - Edit_dist
        - CDM
    table:
      metric:
        - TEDS
        - Edit_dist
    reading_order:
      metric:
        - Edit_dist
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: ./dataset.json
    prediction:
      data_path: ./mds          # ground truth as predictions = self-test; point at your model's .md files
    match_method: quick_match
'''


async def export(source, root, allow_imbalance=False):
    root = root.resolve()
    from factory.runner.languages import stats,balance_problems
    report=stats(source)
    imbalance=balance_problems(report)
    if imbalance and not allow_imbalance:raise ValueError('; '.join(imbalance))
    taxonomy = Taxonomy()
    staging = root / '.staging'
    shutil.rmtree(staging, ignore_errors=True)
    for name in ('images', 'pdfs', 'mds', 'configs', 'source_content', 'metadata'):
        (staging / name).mkdir(parents=True)
    folders = [p.parent for p in sorted((source/'documents').glob('*/*/document.json')) if json.loads((p.parent/'spec.json').read_text()).get('design') == 'agent']
    if not folders: raise ValueError('No accepted agent-designed bundles')
    gate = asyncio.Semaphore(JOBS)
    raw = {}
    for f in folders:
        spec = json.loads((f / 'spec.json').read_text())
        src = f / 'source_content.json'
        if src.exists():
            (staging / 'source_content' / spec['doc_type']).mkdir(exist_ok=True)
            shutil.copy(src, staging / 'source_content' / spec['doc_type'] / f'{f.name}.json')
            raw[f.name] = json.loads(src.read_text())['values']
    async with Browser() as browser:
        results = await asyncio.gather(*(process(browser, taxonomy, f, staging, gate, raw.get(f.name, {})) for f in folders))
    pages, docs, problems = [], [], []
    for result, issues in results:
        problems += issues
        if result:
            pages += result[0]; docs.append(result[1])
    counts = Counter(d['category_type'] for p in pages for d in p['layout_dets'])
    omni = set(['title', 'text_block', 'figure', 'figure_caption', 'figure_footnote', 'table', 'table_caption',
               'table_footnote', 'equation_isolated', 'equation_caption', 'header', 'footer', 'page_number', 'page_footnote',
               'abandon', 'code_txt', 'code_txt_caption', 'reference'])
    problems += check(staging, pages, omni)
    (staging/'metadata/languages.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (staging / 'dataset.json').write_text(json.dumps(pages, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (staging / 'VERSION').write_text(VERSION + '\n')
    (staging / 'configs/end2end.yaml').write_text(end2end())
    with open(staging / 'metadata/documents.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(docs[0]))
        w.writeheader(); w.writerows(docs)
    with open(staging / 'metadata/pages.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['image', 'doc_id', 'page', 'role', 'layout', 'colorful_background', 'blocks'])
        for p in pages:
            i = p['page_info']
            w.writerow([i['image_path'], i['factory']['doc_id'], i['page_no'] + 1, i['factory']['page_role'],
                        i['page_attribute']['layout'], i['page_attribute']['colorful_backgroud'], len(p['layout_dets'])])
    stats = dict(version=VERSION, documents=len(docs), pages=len(pages), categories=dict(counts.most_common()),
                 layouts=dict(Counter(p['page_info']['page_attribute']['layout'] for p in pages)),
                 colorful_background=sum(p['page_info']['page_attribute']['colorful_backgroud'] for p in pages),
                 by_industry=dict(Counter(d['industry'] for d in docs)), by_size=dict(Counter(d['company_size'] for d in docs)),
                 by_theme=dict(Counter(d['theme'] for d in docs)))
    (staging / 'metadata/stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (staging / 'README.md').write_text(readme(pages, docs, counts), encoding='utf-8')
    if problems:
        (staging / 'BUILD_PROBLEMS.txt').write_text('\n'.join(problems) + '\n')
        print(f'{len(problems)} problems; staging kept at {staging}')
        print('\n'.join(problems[:25]))
        return 1
    # Replace the previous generated items, then write checksums over the finished folder.
    for item in GENERATED:
        target = root / item
        shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    for item in GENERATED:
        if (staging / item).exists():
            (root / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(staging / item, root / item)
    shutil.rmtree(staging)
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n'
                   for p in sorted(root.rglob('*')) if p.is_file() and p.name not in ('checksums.sha256', '.DS_Store'))
    (root / 'checksums.sha256').write_text(sums)
    print(f'built {len(docs)} documents, {len(pages)} pages, {sum(counts.values())} blocks')
    print(json.dumps(stats['layouts']), 'colorful', stats['colorful_background'])
    return 0


