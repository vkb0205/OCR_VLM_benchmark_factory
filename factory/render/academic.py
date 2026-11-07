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
    count = len(value.get("labels", []))
    width, height = 440, 210
    if kind in {"pipeline", "block_diagram"}: width = max(width, count * 105)
    if kind == "flowchart": height = max(height, count * 62)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">']
    out.append(_panel_content(rng, kind, value.get('labels', []), 8, 8, width - 16, height - 16))
    return ''.join(out) + '</svg>'


def _panel_content(rng, kind, labels, x, y, width, height):
    labels = labels or ['input', 'process', 'output']
    out = []
    if kind in {'block_diagram', 'architecture', 'flowchart', 'pipeline'}:
        count = len(labels)
        ink = '#42566e'
        def edge(points, dashed=False):
            dash = ' stroke-dasharray="4 3"' if dashed else ''
            out.append(f'<path d="{points}" fill="none" stroke="{ink}" stroke-width="1.4"{dash} marker-end="url(#arrow)"/>')
        def node(bx, by, bw, bh, label, shape='box'):
            if shape == 'diamond':
                outline = f'<path d="M{bx+bw/2},{by} L{bx+bw},{by+bh/2} L{bx+bw/2},{by+bh} L{bx},{by+bh/2}Z"'
            elif shape == 'document':
                outline = f'<path d="M{bx},{by} H{bx+bw} V{by+bh-5} Q{bx+bw*.75},{by+bh-12} {bx+bw/2},{by+bh-5} T{bx},{by+bh-5}Z"'
            else:
                outline = f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="3"'
            out.append(outline + f' fill="#edf2f5" stroke="{ink}"/>')
            if shape == 'cylinder':
                out.append(f'<ellipse cx="{bx+bw/2}" cy="{by+4}" rx="{bw/2}" ry="4" fill="#edf2f5" stroke="{ink}"/>')
            import textwrap
            lines = textwrap.wrap(label, max(7, int(bw/5))) or ['']
            for i,line in enumerate(lines):
                out.append(f'<text x="{bx+bw/2}" y="{by+bh/2+(i-(len(lines)-1)/2)*10+3}" text-anchor="middle" font-size="9">{escape(line)}</text>')
        out.append('<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7Z" fill="#42566e"/></marker></defs>')
        if kind == 'flowchart':
            step = height / count
            bw, bh = width*.44, step*.65
            bx = x+width*.22
            for i,label in enumerate(labels):
                by=y+i*step+2
                decision = 0 < i < count-1 and i % 2 == 1
                node(bx,by,bw,bh,label,'diamond' if decision else 'box')
                if i < count-1:
                    edge(f'M{bx+bw/2},{by+bh} V{y+(i+1)*step+2}')
                if decision:
                    right=x+width*.93
                    edge(f'M{bx+bw},{by+bh/2} H{right} V{y+2} H{bx+bw/2}',True)
                    out.append(f'<text x="{bx+bw+5}" y="{by+bh/2-4}" font-size="9">No</text><text x="{bx+bw/2+4}" y="{by+bh+9}" font-size="9">Yes</text>')
        elif kind == 'pipeline':
            step=width/count; bw=step*.78; bh=height*.30
            for i,label in enumerate(labels):
                bx=x+i*step+2; by=y+height*.30
                node(bx,by,bw,bh,label,'cylinder' if i==0 else 'document' if i==count-1 else 'box')
                if 0<i<count-1:
                    for j in range(2):
                        out.append(f'<rect x="{bx+4+j*3}" y="{by+bh+6+j*7}" width="{bw-8}" height="5" fill="#d7e1e8" stroke="{ink}"/>')
                if i<count-1: edge(f'M{bx+bw},{by+bh/2} H{x+(i+1)*step+2}')
        elif kind == 'architecture':
            split=max(1,math.ceil(count/2))
            gap=height*.08; rowh=(height-gap*3)/2
            for row,group in enumerate((labels[:split],labels[split:])):
                if not group: continue
                gy=y+gap+row*(rowh+gap)
                out.append(f'<rect x="{x+width*.06}" y="{gy}" width="{width*.83}" height="{rowh}" rx="6" fill="#f7f8fa" stroke="{ink}" stroke-dasharray="4 2"/>')
                step=width*.77/len(group)
                for i,label in enumerate(group):
                    bx=x+width*.09+i*step
                    node(bx,gy+rowh*.25,step*.87,rowh*.5,label)
                    if i: edge(f'M{bx-step*.13},{gy+rowh/2} H{bx}')
            if count>1:
                edge(f'M{x+width*.47},{y+gap+rowh} V{y+2*gap+rowh}')
                edge(f'M{x+width*.89},{y+gap+rowh/2} H{x+width*.97} V{y+2*gap+rowh*1.5} H{x+width*.89}',True)
        else:
            step=width/(count+1); bw=step*.75; bh=height*.28
            cy=y+height*.43; junction=x+step*.45
            out.append(f'<circle cx="{junction}" cy="{cy}" r="9" fill="white" stroke="{ink}"/><text x="{junction}" y="{cy+3}" text-anchor="middle" font-size="11">+</text>')
            edge(f'M{junction+9},{cy} H{x+step}')
            for i,label in enumerate(labels):
                bx=x+(i+1)*step
                node(bx,cy-bh/2,bw,bh,label)
                if i<count-1: edge(f'M{bx+bw},{cy} H{bx+step}')
            last=x+count*step+bw
            edge(f'M{last},{cy} V{y+height*.88} H{junction} V{cy+9}')
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
