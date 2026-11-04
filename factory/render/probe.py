PAGE_PROBE = """() => {
    const text = new Set(TEXT_CATS), b = document.body.getBoundingClientRect(), out = {bg: {}, problems: []};
    const rgba = c => (c.match(/[\\d.]+/g) || []).map(Number);
    const fill = n => {
        const s = getComputedStyle(n);
        if (s.backgroundImage && s.backgroundImage !== 'none') return s.backgroundImage.includes('url(') ? 'image' : 'multi_color';
        const [r, g, bl, a = 1] = rgba(s.backgroundColor);
        if (s.backgroundColor === 'transparent' || a < 0.05) return null;
        return r > 244 && g > 244 && bl > 244 ? 'white' : 'single_color';
    };
    for (const e of document.querySelectorAll('[data-gt-cat]')) {
        const id = e.dataset.gtId, r = e.getBoundingClientRect();
        if (!id) continue;
        if (text.has(e.dataset.gtCat) && r.width && r.height) {
            // Whatever is painted under the block's center: itself, an ancestor or a decoration.
            const stack = document.elementsFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            let label = 'white';
            for (const n of stack) {
                if (n !== e && e.contains(n)) continue;
                const value = fill(n);
                if (value) { label = value; break; }
            }
            out.bg[id] = label;
        }
        for (const art of e.querySelectorAll(':scope > svg, :scope > img')) {
            const a = art.getBoundingClientRect(), spill = Math.max(a.bottom - r.bottom, a.right - r.right, r.top - a.top, r.left - a.left);
            if (r.height && spill > 1) out.problems.push(`block ${id}: its drawing spills ${Math.round(spill * 25.4 / 96)} mm outside its box (set a height the drawing fits, or let it scale)`);
        }
        if (r.bottom > b.bottom + .5 || r.right > b.right + .5 || r.left < b.left - .5 || r.top < b.top - .5)
        {
            const mm = x => Math.round(x * 25.4 / 96);
            const sides = [['bottom', r.bottom - b.bottom], ['right', r.right - b.right], ['left', b.left - r.left], ['top', b.top - r.top]]
                .filter(([, v]) => v > .5).sort((x, y) => y[1] - x[1]);
            let why = '';
            if (sides[0] && ['right', 'left'].includes(sides[0][0])) {
                const box = e.parentElement ? e.parentElement.getBoundingClientRect() : null;
                if (box && box.width + 1 < r.width) why = ` (it is ${mm(r.width)} mm wide but its container is only ${mm(box.width)} mm wide)`;
            }
            out.problems.push(`block ${id} extends outside the page by ${mm(sides.length ? sides[0][1] : 0)} mm on the ${sides.length ? sides[0][0] : 'bottom'}${why}`);
        }
    }
    // A container is too small if it clips content, or if in-flow blocks spill past it.
    // Absolutely positioned blocks (a seal over a signature) may overlap on purpose.
    const seen = new Set();
    const inFlow = (e, n) => {
        for (let x = e; x && x !== n; x = x.parentElement)
            if (['absolute', 'fixed'].includes(getComputedStyle(x).position)) return false;
        return true;
    };
    for (const e of document.querySelectorAll('[data-gt-cat]')) {
        for (let n = e.parentElement; n && n !== document.body; n = n.parentElement) {
            if (seen.has(n)) continue;
            const box = n.getBoundingClientRect(), clips = getComputedStyle(n).overflow !== 'visible';
            const spill = Math.max(0, ...[...n.querySelectorAll('[data-gt-cat]')].filter(c => inFlow(c, n))
                .map(c => c.getBoundingClientRect().bottom - box.bottom));
            const extra = clips ? n.scrollHeight - n.clientHeight : spill;
            if (extra <= 1) continue;
            seen.add(n);
            const mm = Math.max(1, Math.round(extra * 25.4 / 96));
            const name = n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).split(' ').join('.') : '');
            let detail = '';
            for (const t of n.querySelectorAll('table[data-gt-cat]')) {
                const rows = [...t.tBodies[0].rows], over = rows.filter(row => row.getBoundingClientRect().bottom > box.bottom + .5).length;
                if (over) detail += `; table ${t.dataset.gtId}: the last ${over} of its ${rows.length} rows here do not fit`;
            }
            out.problems.push(`<${name}> content is ${mm} mm taller than its box${detail}`);
        }
    }
    return out;
}"""

