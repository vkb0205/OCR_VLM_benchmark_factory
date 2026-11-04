"""Offline HTML/SVG helpers for academic paper components."""
from html import escape
import math


def spans_html(spans):
    """Render normalized inline spans without assigning ground-truth labels."""
    out = []
    for span in spans:
        kind = span.get('type', 'text')
        if kind == 'text':
            out.append(escape(span.get('text', '')))
        elif kind == 'equation_inline':
            latex = escape(span['latex'], quote=True)
            out.append(f'<span class="factory-math" data-formula="{latex}"></span>')
        elif kind == 'footnote_mark':
            target = escape(span.get('target') or '', quote=True)
            out.append(f'<sup class="factory-footnote-mark" data-target-id="{target}">{escape(span["text"])}</sup>')
    return ''.join(out)


def table_fragment(table):
    def cell(value, tag):
        attrs = ''
        if value.get('colspan', 1) != 1:
            attrs += f' colspan="{value["colspan"]}"'
        if value.get('rowspan', 1) != 1:
            attrs += f' rowspan="{value["rowspan"]}"'
        text = escape(value['text'])
        if value.get('bold'):
            text = f'<strong>{text}</strong>'
        return f'<{tag}{attrs}>{text}</{tag}>'

    header = ''.join('<tr>' + ''.join(cell(value, 'th') for value in row) + '</tr>' for row in table['header'])
    rows = ['<tr>' + ''.join(cell(value, 'td') for value in row) + '</tr>' for row in table['rows']]
    return f'<thead>{header}</thead><tbody>{"".join(rows)}</tbody>', rows


def _rgb(value):
    value = max(0, min(255, round(value)))
    return f'{value:02x}'


def _blend(a, b, t):
    left = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
    right = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
    return '#' + ''.join(_rgb(x + (y - x) * t) for x, y in zip(left, right))


def figure_svg(rng, value):
    """Draw a seeded diagram, architecture, synthetic image panel, or panel grid."""
    kind = value['figure_type']
    if kind == 'multi_panel':
        columns = 2 if len(value['panels']) <= 2 else 3
        rows = math.ceil(len(value['panels']) / columns)
        panel_w, panel_h = 210, 160
        width, height = columns * panel_w + 20, rows * panel_h + 20
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">']
        for index, panel in enumerate(value['panels']):
            x, y = 10 + (index % columns) * panel_w, 10 + (index // columns) * panel_h
            out.append(f'<g transform="translate({x},{y})"><rect width="196" height="142" fill="#fff" stroke="#687483"/>')
            out.append(f'<text x="8" y="18" font-size="13" font-weight="700">({chr(97 + index)})</text>')
            out.append(_panel_content(rng, panel['figure_type'], panel.get('labels', []), 18, 34, 162, 96))
            out.append('</g>')
        return ''.join(out) + '</svg>'
    width, height = 440, 210
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">']
    out.append(_panel_content(rng, kind, value.get('labels', []), 8, 8, width - 16, height - 16))
    return ''.join(out) + '</svg>'


def _panel_content(rng, kind, labels, x, y, width, height):
    labels = labels or ['input', 'process', 'output']
    out = []
    if kind in {'block_diagram', 'architecture'}:
        count = len(labels)
        box_w = min(112, (width - (count - 1) * 24) / count)
        y0 = y + height * .36
        for index, label in enumerate(labels):
            bx = x + index * (box_w + 18)
            fill = ('#e8eef4', '#e9f0e9', '#f4eee2')[index % 3]
            out.append(f'<rect x="{bx:.1f}" y="{y0:.1f}" width="{box_w:.1f}" height="{height * .30:.1f}" rx="5" fill="{fill}" stroke="#42566e"/>')
            out.append(f'<text x="{bx + box_w / 2:.1f}" y="{y0 + height * .18:.1f}" text-anchor="middle" font-size="11">{escape(label)}</text>')
            if index < count - 1:
                ax = bx + box_w
                out.append(f'<path d="M{ax + 2:.1f},{y0 + height * .15:.1f} H{ax + 15:.1f}" fill="none" stroke="#42566e" stroke-width="1.5" marker-end="url(#arrow)"/>')
        out.insert(0, '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7Z" fill="#42566e"/></marker></defs>')
        if kind == 'architecture':
            for index, label in enumerate(labels):
                bx = x + index * (width / max(1, len(labels))) + 10
                out.append(f'<text x="{bx:.1f}" y="{y + 14:.1f}" font-size="8" fill="#677487">layer {index + 1}</text>')
        return ''.join(out)
    # Deterministic image-like evidence: a heat field with a synthetic contour.
    cols, rows = 16, 9
    cw, ch = width / cols, height / rows
    for row in range(rows):
        for col in range(cols):
            noise = rng.random() * .18
            mound = math.exp(-(((col - cols * .57) / 5.5) ** 2 + ((row - rows * .48) / 3.2) ** 2))
            value = max(0, min(1, .12 + .72 * mound + noise))
            color = _blend('#f7f6ef', '#477e89', value)
            out.append(f'<rect x="{x + col * cw:.1f}" y="{y + row * ch:.1f}" width="{cw + .2:.1f}" height="{ch + .2:.1f}" fill="{color}"/>')
    # Contours are procedural polylines; they carry no hidden text.
    for level in range(3):
        points = []
        for step in range(17):
            px = x + width * step / 16
            py = y + height * (.28 + level * .18 + .035 * math.sin(step * .62 + level))
            points.append(f'{px:.1f},{py:.1f}')
        out.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#243b48" stroke-opacity=".65" stroke-width="1"/>')
    if labels:
        out.append(f'<text x="{x + 4:.1f}" y="{y + height - 4:.1f}" font-size="9" fill="#16242b">{escape(labels[0])}</text>')
    return ''.join(out)
