"""Shared export-compatible browser capture and block geometry."""

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

async def measure_blocks(page, text_categories, dpi=200):
    """Keep export's historical payload and rounding unchanged at 200 DPI."""
    script = CAPTURE if dpi == 200 else CAPTURE.replace('s = 200 / 96', f's = {dpi} / 96')
    return await page.evaluate(script, sorted(text_categories))
