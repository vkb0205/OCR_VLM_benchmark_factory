"""Light SVG for charts, logos, signatures and seals; seeded, offline, no image model."""

from contextvars import ContextVar
from html import escape
import math

# Language of the document being rendered; fill() sets it, so chart numbers match the text (vi 1.900,5 / en 1,900.5).
LANG: ContextVar[str] = ContextVar("chart_lang", default="vi")
# Design-drawn chart style: {"colors": (..), "forms": {"bar": "hbar", "line": "area", ...}}; None = defaults.
STYLE: ContextVar[dict | None] = ContextVar("chart_style", default=None)


def styled(data: dict, colors):
    """Apply the design's chart form and colours; the data and its ground truth keep the same values."""
    style = STYLE.get()
    if not style:
        return data, colors
    data = dict(data)
    data["chart_type"] = style.get("forms", {}).get(data["chart_type"], data["chart_type"])
    if data["chart_type"] == "donut" and len(data.get("series", [])) != 1:
        data["chart_type"] = "bar"
    return data, tuple(style.get("colors") or colors)

PALETTES = [("#1f4e79", "#c9a227"), ("#2f6b3f", "#9cc5a1"), ("#7a1f2b", "#e0a96d"),
            ("#3b3b98", "#7ec4cf"), ("#444444", "#d08c3c"), ("#0b6e69", "#f2c14e")]


def number(value: float) -> str:
    text = f"{value:,.1f}".rstrip("0").rstrip(".")
    if LANG.get() == "en":
        return text
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _legend_text(x: float, y: float, text: str, room: float, size: float = 10) -> str:
    """Legend label; squeezed with textLength when it would run past `room` units (the text is unchanged)."""
    fit = f' textLength="{room:.1f}" lengthAdjust="spacingAndGlyphs"' if len(text) * size * 0.55 > room else ""
    return f'<text x="{x}" y="{y}"{fit}>{escape(text)}</text>'


def _axis_label(x: float, y: float, text: str, room: float, size: float = 10) -> str:
    """Centered category label: one line, or two lines split at a space, squeezed only if still too wide."""
    width = lambda value: len(value) * size * 0.55
    if width(text) <= room:
        return f'<text x="{x:.1f}" y="{y}" text-anchor="middle">{escape(text)}</text>'
    words = text.split()
    if len(words) > 1:
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    else:
        lines = [text]
    spans = []
    for index, line in enumerate(lines):
        fit = f' textLength="{room:.1f}" lengthAdjust="spacingAndGlyphs"' if width(line) > room else ""
        dy = 0 if index == 0 else size + 1
        spans.append(f'<tspan x="{x:.1f}" dy="{dy}"{fit}>{escape(line)}</tspan>')
    return f'<text x="{x:.1f}" y="{y - (size / 2 if len(lines) > 1 else 0):.1f}" text-anchor="middle">{"".join(spans)}</text>'


def _legacy_chart_svg(data: dict, colors=("#1f4e79", "#c9a227", "#7a7a7a")) -> str:
    """Bar, line or donut chart. Text is real SVG text, so it stays inside the chart block."""
    kind, labels, series = data["chart_type"], data["labels"], data["series"]
    w, h, left, bottom, top = 400, 220, 44, 30, 26
    names = [str(s["name"]) for s in series]
    # Legend in one row when every name fits its 120-unit cell, otherwise one name per row above the plot.
    stacked = kind != "donut" and any(len(name) * 5.5 > 103 for name in names)
    if stacked:
        top = 12 + 12 * len(names)
        h += top - 26
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" '
           'font-family="Factory Serif, serif" font-size="10">']
    for i, name in enumerate(names):
        x, y = (left, 6 + 12 * i) if stacked else (left + i * 120, 6)
        room = w - x - 23 if stacked else min(120, w - x) - 17
        out.append(f'<rect x="{x}" y="{y}" width="9" height="9" fill="{colors[i % len(colors)]}"/>'
                   + _legend_text(x + 13, y + 8, name, room))
    if kind == "donut":
        values = series[0]["values"]
        total = sum(values) or 1
        cx, cy, r, angle = 120, 125, 75, -math.pi / 2
        shades = [colors[0], colors[1], "#9aa5b1", "#5b6b7a", "#d9c9a3", "#8e6c8a"]
        for i, (label, value) in enumerate(zip(labels, values)):
            sweep = 2 * math.pi * value / total
            end = angle + sweep
            x1, y1, x2, y2 = cx + r * math.cos(angle), cy + r * math.sin(angle), cx + r * math.cos(end), cy + r * math.sin(end)
            out.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{r},{r} 0 {int(sweep > math.pi)} 1 {x2:.1f},{y2:.1f} Z" '
                       f'fill="{shades[i % len(shades)]}"/>')
            out.append(f'<rect x="240" y="{46 + i * 18}" width="9" height="9" fill="{shades[i % len(shades)]}"/>'
                       + _legend_text(254, 54 + i * 18, f"{label}: {number(value)}", w - 254 - 4))
            angle = end
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r * .55}" fill="white"/></svg>')
        return "".join(out)
    if kind == "stacked_bar":
        peak = max((sum(max(0, s["values"][j]) for s in series) for j in range(len(labels))), default=1) or 1
    else:
        peak = max((v for s in series for v in s["values"]), default=1) or 1
    if kind == "hbar":
        return "".join(out) + _hbar(labels, series, colors, peak, w, h, top)
    plot_w, plot_h = w - left - 10, h - bottom - top
    for k in range(5):
        y = top + plot_h - plot_h * k / 4
        out.append(f'<line x1="{left}" x2="{w - 10}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>'
                   f'<text x="{left - 4}" y="{y + 3:.1f}" text-anchor="end">{number(peak * k / 4)}</text>')
    step = plot_w / max(len(labels), 1)
    for j, label in enumerate(labels):
        out.append(_axis_label(left + step * (j + .5), h - 12, str(label), step - 4))
    base = top + plot_h
    y_of = lambda v: base - plot_h * max(0, v) / peak
    stack = [0.0] * len(labels)
    for i, s in enumerate(series):
        color = colors[i % len(colors)]
        xs = [left + step * (j + .5) for j in range(len(s["values"]))]
        if kind in {"line", "area"}:
            points = " ".join(f"{x:.1f},{y_of(v):.1f}" for x, v in zip(xs, s["values"]))
            if kind == "area":
                out.append(f'<polygon points="{xs[0]:.1f},{base:.1f} {points} {xs[-1]:.1f},{base:.1f}" '
                           f'fill="{color}" fill-opacity=".3"/>')
            out.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        elif kind == "stacked_bar":
            for j, v in enumerate(s["values"]):
                height = plot_h * max(0, v) / peak
                y = base - plot_h * stack[j] / peak - height
                stack[j] += max(0, v)
                out.append(f'<rect x="{xs[j] - step * .3:.1f}" y="{y:.1f}" width="{step * .6:.1f}" '
                           f'height="{height:.1f}" fill="{color}"/>')
        elif kind in {"dot", "lollipop"}:
            shift = (i - (len(series) - 1) / 2) * min(10, step * .5 / max(len(series), 1))
            for x, v in zip(xs, s["values"]):
                if kind == "lollipop":
                    out.append(f'<line x1="{x + shift:.1f}" x2="{x + shift:.1f}" y1="{base:.1f}" y2="{y_of(v):.1f}" '
                               f'stroke="{color}" stroke-width="2"/>')
                out.append(f'<circle cx="{x + shift:.1f}" cy="{y_of(v):.1f}" r="4.5" fill="{color}"/>')
            if kind == "dot" and len(xs) > 1:
                points = " ".join(f"{x + shift:.1f},{y_of(v):.1f}" for x, v in zip(xs, s["values"]))
                out.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1" '
                           'stroke-dasharray="3 3"/>')
        else:
            bar = step * .7 / len(series)
            for j, v in enumerate(s["values"]):
                x = left + step * j + step * .15 + bar * i
                out.append(f'<rect x="{x:.1f}" y="{top + plot_h - plot_h * v / peak:.1f}" width="{bar:.1f}" '
                           f'height="{plot_h * v / peak:.1f}" fill="{color}"/>')
    out.append("</svg>")
    return "".join(out)


def _hbar(labels, series, colors, peak, w, h, top) -> str:
    """Horizontal bars: categories down the left, value gridlines across."""
    left, right, bottom = 78, 14, 20
    plot_w, plot_h = w - left - right, h - top - bottom
    out = []
    for k in range(5):
        x = left + plot_w * k / 4
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top + plot_h}" stroke="#ddd"/>'
                   f'<text x="{x:.1f}" y="{h - 6}" text-anchor="middle">{number(peak * k / 4)}</text>')
    step = plot_h / max(len(labels), 1)
    bar = step * .7 / max(len(series), 1)
    for j, label in enumerate(labels):
        text = str(label)
        fit = f' textLength="{left - 8}" lengthAdjust="spacingAndGlyphs"' if len(text) * 5.5 > left - 8 else ""
        out.append(f'<text x="{left - 4}" y="{top + step * (j + .5) + 3:.1f}" text-anchor="end"{fit}>{escape(text)}</text>')
        for i, s in enumerate(series):
            value = max(0, s["values"][j])
            out.append(f'<rect x="{left}" y="{top + step * j + step * .15 + bar * i:.1f}" '
                       f'width="{plot_w * value / peak:.1f}" height="{bar:.1f}" fill="{colors[i % len(colors)]}"/>')
    return "".join(out) + "</svg>"


FORMS = {"bar", "line", "donut", "hbar", "dot", "lollipop", "area", "stacked_bar"}


def chart_svg(data: dict, colors=("#1f4e79", "#c9a227", "#7a7a7a")) -> str:
    """Render an offline chart; retain the financial-report SVG byte path."""
    kind = data['chart_type']
    if not data.get('academic') and kind in FORMS:
        return _legacy_chart_svg(data, colors)
    return _academic_chart_svg(data, colors)


def _academic_chart_svg(data, colors):
    kind, labels, series = data['chart_type'], data.get('labels', []), data['series']
    width = 520
    outside_legend = data.get('legend_position', 'outside') == 'outside'
    x_label = data.get('x_label')
    height = 340 if outside_legend and x_label else 326 if outside_legend else 310
    left, right, top = 58, 28, 40
    bottom = 82 if outside_legend and x_label else 68 if outside_legend else 56
    plot_w, plot_h = width - left - right, height - top - bottom
    y_label = data.get('y_label')
    gridlines = data.get('gridlines', True)
    legend_position = data.get('legend_position', 'outside')
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" font-family="Factory Serif, serif" font-size="11">']

    if kind == 'donut':
        values = series[0]['values']
        total = sum(values) or 1
        cx, cy, radius, angle = 170, 153, 112, -math.pi / 2
        colors_for_slices = list(colors) + ['#9aa5b1', '#5b6b7a', '#d9c9a3', '#8e6c8a']
        for index, (label, value) in enumerate(zip(labels, values)):
            sweep = 2 * math.pi * value / total
            end = angle + sweep
            x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            x2, y2 = cx + radius * math.cos(end), cy + radius * math.sin(end)
            color = colors_for_slices[index % len(colors_for_slices)]
            out.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{radius},{radius} 0 {int(sweep > math.pi)} 1 {x2:.1f},{y2:.1f} Z" fill="{color}" stroke="white" stroke-width="1.5"/>')
            out.append(f'<rect x="326" y="{70 + index * 23}" width="11" height="11" fill="{color}"/><text x="344" y="{80 + index * 23}">{escape(str(label))}: {number(value)}</text>')
            angle = end
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{radius * .48:.1f}" fill="white"/>')
        return ''.join(out) + '</svg>'

    all_y = []
    if kind == 'scatter':
        all_y = [point[1] for item in series for point in item['points']]
        all_x = [point[0] for item in series for point in item['points']]
        x_min, x_max = min(all_x), max(all_x)
        x_min, x_max = (x_min - .5, x_max + .5) if x_min == x_max else (x_min, x_max)
    elif kind == 'box':
        all_y = [value for item in series for group in item['stats'] for value in group]
        x_min, x_max = -.5, max(0.5, len(labels) - .5)
    else:
        all_y = [value for item in series for value in item['values']]
        x_min, x_max = -.5, max(0.5, len(labels) - .5)
    if kind in {'bar', 'grouped_bar', 'stacked_bar', 'histogram', 'donut'}:
        y_min = 0
    else:
        y_min = min(0, min(all_y, default=0))
    y_max = max(all_y, default=1)
    if kind in {'line','bar','grouped_bar'}:
        y_max = max([y_max] + [v+e for item in series for v,e in zip(item.get('values',[]),item.get('errors',[]))])
    if kind == 'stacked_bar':
        y_max = max((sum(item['values'][i] for item in series) for i in range(len(labels))), default=1)
    if y_max <= y_min:
        y_max = y_min + 1
    pad = (y_max - y_min) * .08
    y_max += pad
    if y_min < 0:
        y_min -= pad
    def xp(value): return left + plot_w * (value - x_min) / (x_max - x_min)
    def yp(value): return top + plot_h * (y_max - value) / (y_max - y_min)

    # Horizontal tick labels and optional gridlines.
    for tick in range(5):
        value = y_min + (y_max - y_min) * tick / 4
        y = yp(value)
        if gridlines:
            out.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="#d9dde2"/>')
        out.append(f'<text x="{left - 7}" y="{y + 3:.1f}" text-anchor="end" fill="#303943">{number(value)}</text>')
    zero_y = yp(0) if y_min <= 0 <= y_max else top + plot_h
    out.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="#5c6672"/>')
    if kind != 'scatter':
        for index, label in enumerate(labels):
            x = xp(index)
            out.append(f'<text x="{x:.1f}" y="{top + plot_h + 19}" text-anchor="middle" fill="#303943">{escape(str(label))}</text>')
    else:
        for tick in range(5):
            value = x_min + (x_max - x_min) * tick / 4
            out.append(f'<text x="{xp(value):.1f}" y="{top + plot_h + 19}" text-anchor="middle">{number(value)}</text>')
    out.append(f'<line x1="{left}" x2="{left}" y1="{top}" y2="{top + plot_h}" stroke="#5c6672"/>')
    out.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{top + plot_h}" y2="{top + plot_h}" stroke="#5c6672"/>')

    if kind in {'bar', 'grouped_bar', 'histogram', 'stacked_bar'}:
        group_w = plot_w / max(1, len(labels))
        if kind == 'stacked_bar':
            bar_w = group_w * .62
            for index in range(len(labels)):
                current = 0
                for series_index, item in enumerate(series):
                    value = item['values'][index]
                    y_top = yp(current + value)
                    y_bottom = yp(current)
                    out.append(f'<rect x="{xp(index) - bar_w / 2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{max(0,y_bottom-y_top):.1f}" fill="{colors[series_index % len(colors)]}" stroke="white" stroke-width=".6"/>')
                    current += value
        else:
            nseries = len(series) if kind == 'grouped_bar' else 1
            bar_w = group_w if kind == "histogram" else group_w * .68 / nseries
            for series_index, item in enumerate(series):
                for index, value in enumerate(item['values']):
                    offset = (series_index - (nseries - 1) / 2) * bar_w
                    x = xp(index) + offset - bar_w / 2
                    y = yp(value)
                    out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(0,zero_y-y):.1f}" fill="{colors[series_index % len(colors)]}"/>')
                    if item.get('errors'):
                        ey1, ey2 = yp(value + item['errors'][index]), yp(value - item['errors'][index])
                        mid = x + bar_w / 2
                        out.append(f'<line x1="{mid:.1f}" x2="{mid:.1f}" y1="{ey1:.1f}" y2="{ey2:.1f}" stroke="#202a33"/><line x1="{mid-4:.1f}" x2="{mid+4:.1f}" y1="{ey1:.1f}" y2="{ey1:.1f}" stroke="#202a33"/><line x1="{mid-4:.1f}" x2="{mid+4:.1f}" y1="{ey2:.1f}" y2="{ey2:.1f}" stroke="#202a33"/>')
    elif kind in {'line', 'area'}:
        for series_index, item in enumerate(series):
            points = [(xp(index), yp(value)) for index, value in enumerate(item['values'])]
            encoded = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
            color = colors[series_index % len(colors)]
            if kind == 'area':
                baseline = zero_y
                path = f'M{points[0][0]:.1f},{baseline:.1f} L' + ' L'.join(f'{x:.1f},{y:.1f}' for x,y in points) + f' L{points[-1][0]:.1f},{baseline:.1f} Z'
                out.append(f'<path d="{path}" fill="{color}" fill-opacity=".16" stroke="none"/>')
            out.append(f'<polyline points="{encoded}" fill="none" stroke="{color}" stroke-width="2.2"/>')
            for index, (x, y) in enumerate(points):
                if item.get('errors'):
                    y1, y2 = yp(item['values'][index] + item['errors'][index]), yp(item['values'][index] - item['errors'][index])
                    out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y1:.1f}" y2="{y2:.1f}" stroke="{color}"/><line x1="{x-4:.1f}" x2="{x+4:.1f}" y1="{y1:.1f}" y2="{y1:.1f}" stroke="{color}"/><line x1="{x-4:.1f}" x2="{x+4:.1f}" y1="{y2:.1f}" y2="{y2:.1f}" stroke="{color}"/>')
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.1" fill="white" stroke="{color}" stroke-width="1.8"/>')
    elif kind == 'scatter':
        for series_index, item in enumerate(series):
            color = colors[series_index % len(colors)]
            for x, y in item['points']:
                out.append(f'<circle cx="{xp(x):.1f}" cy="{yp(y):.1f}" r="3.3" fill="{color}" fill-opacity=".82"/>')
    elif kind == 'box':
        group_w = plot_w / max(1, len(labels)); box_w = group_w * .46 / len(series)
        for series_index, item in enumerate(series):
            color = colors[series_index % len(colors)]
            for index, stat in enumerate(item['stats']):
                low, q1, median, q3, high = stat
                center = xp(index) + (series_index - (len(series) - 1) / 2) * box_w
                out.append(f'<line x1="{center:.1f}" x2="{center:.1f}" y1="{yp(high):.1f}" y2="{yp(low):.1f}" stroke="{color}"/>')
                out.append(f'<rect x="{center-box_w/2:.1f}" y="{yp(q3):.1f}" width="{box_w:.1f}" height="{max(1,yp(q1)-yp(q3)):.1f}" fill="{color}" fill-opacity=".25" stroke="{color}"/>')
                out.append(f'<line x1="{center-box_w/2:.1f}" x2="{center+box_w/2:.1f}" y1="{yp(median):.1f}" y2="{yp(median):.1f}" stroke="{color}" stroke-width="2"/>')
                out.append(f'<line x1="{center-box_w/3:.1f}" x2="{center+box_w/3:.1f}" y1="{yp(high):.1f}" y2="{yp(high):.1f}" stroke="{color}"/><line x1="{center-box_w/3:.1f}" x2="{center+box_w/3:.1f}" y1="{yp(low):.1f}" y2="{yp(low):.1f}" stroke="{color}"/>')

    if legend_position in {'outside', 'inside'}:
        for index, item in enumerate(series):
            lx = left + 5 if legend_position == 'inside' else left + index * (plot_w / max(1, len(series)))
            ly = top + 13 if legend_position == 'inside' else height - (24 if x_label else 7)
            out.append(f'<line x1="{lx}" x2="{lx+14}" y1="{ly-3}" y2="{ly-3}" stroke="{colors[index % len(colors)]}" stroke-width="2.5"/>')
            out.append(f'<text x="{lx+19}" y="{ly}">{escape(item["name"])}</text>')
    if x_label:
        out.append(f'<text x="{left + plot_w/2:.1f}" y="{height-1}" text-anchor="middle" font-size="12">{escape(x_label)}</text>')
    if y_label:
        out.append(f'<text x="14" y="{top + plot_h/2:.1f}" text-anchor="middle" font-size="12" transform="rotate(-90 14 {top + plot_h/2:.1f})">{escape(y_label)}</text>')
    return ''.join(out) + '</svg>'


def logo_svg(rng, motif: str, colors) -> str:
    """Abstract monogram-free logo, so it carries no text to label."""
    a, b = colors
    shapes = {
        "circle": f'<circle cx="50" cy="50" r="40" fill="{a}"/><circle cx="62" cy="40" r="18" fill="{b}"/>',
        "leaf": f'<path d="M50 8 C85 25 85 75 50 92 C15 75 15 25 50 8Z" fill="{a}"/><path d="M50 18 V84" stroke="{b}" stroke-width="5"/>',
        "diamond": f'<path d="M50 6 L94 50 L50 94 L6 50Z" fill="{a}"/><path d="M50 28 L72 50 L50 72 L28 50Z" fill="{b}"/>',
        "waves": f'<rect x="8" y="8" width="84" height="84" rx="16" fill="{a}"/>'
                 + "".join(f'<path d="M14 {38 + k * 16} Q32 {28 + k * 16} 50 {38 + k * 16} T86 {38 + k * 16}" fill="none" stroke="{b}" stroke-width="5"/>' for k in range(3)),
        "blocks": "".join(f'<rect x="{10 + (k % 3) * 28}" y="{10 + (k // 3) * 28}" width="24" height="24" fill="{(a, b)[rng.random() < .4]}"/>' for k in range(9)),
    }
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{shapes.get(motif, shapes["circle"])}</svg>'


def signature_svg(rng) -> str:
    points = " ".join(f"{10 + j * 14},{rng.randint(20, 65)}" for j in range(10))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90">'
            f'<polyline points="{points}" fill="none" stroke="#223b68" stroke-width="1.8"/>'
            f'<path d="M20 {rng.randint(60, 72)} Q85 50 145 {rng.randint(58, 70)}" fill="none" stroke="#223b68" stroke-width="1.2"/></svg>')


def seal_svg(text: str) -> str:
    """Red ring seal; its ring text is the seal block's ground-truth value."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
            '<defs><path id="ring" d="M25 82 A55 55 0 1 1 135 82 A55 55 0 1 1 25 82"/></defs>'
            '<circle cx="80" cy="80" r="76" fill="none" stroke="#c32332" stroke-width="3"/>'
            '<circle cx="80" cy="80" r="48" fill="none" stroke="#c32332" stroke-width="1.5"/>'
            '<text fill="#c32332" font-family="Factory Serif,serif" font-size="12" letter-spacing="1">'
            f'<textPath href="#ring" startOffset="4%">{escape(text)}</textPath></text>'
            '<path d="M80 53 L87 72 L107 73 L91 85 L96 105 L80 93 L64 105 L69 85 L53 73 L73 72Z" fill="#c32332"/></svg>')

_original_chart_svg = chart_svg
def chart_svg(data, colors=("#1f4e79", "#c9a227", "#7a7a7a")):
    kind=data['chart_type']
    if kind=='donut' and (len(data['series'])!=1 or any(v<0 for v in data['series'][0]['values'])):
        raise ValueError('Donut requires one non-negative series')
    if kind=='grouped_column':return _legacy_chart_svg({**data,'chart_type':'bar'},colors)
    if not data.get('academic') or kind not in {'hbar','dot','lollipop'}:
        return _original_chart_svg(data,colors)
    labels=data['labels'];series=data['series'];n=max(1,len(labels));peak=max(1,max(sum(max(0,s['values'][i]) for s in series) if kind=='stacked_bar' else max(abs(s['values'][i]) for s in series) for i in range(n)))
    out=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 320" font-family="Factory Serif,serif" font-size="11">']
    for i,label in enumerate(labels):
        text=escape(str(label));out.append(f'<text x="{80+420*(i+.5)/n:.2f}" y="305" text-anchor="middle" textLength="{min(100,420/n):.2f}" lengthAdjust="spacingAndGlyphs">{text}</text>')
    stacked=[0]*n
    for k,s in enumerate(series):
        color=escape(colors[k%len(colors)],quote=True);points=[]
        out.append(_legend_text(10+k*160, 15, str(s["name"]), min(160, 520-10-k*160) - 6, 11))
        for i,v in enumerate(s['values']):
            x=80+420*(i+.5)/n;y=280-240*v/peak;points.append((x,y))
            if kind=='hbar':
                y=35+240*(i+(k+.5)/len(series))/n
                out.append(f'<rect x="80" y="{y}" width="{max(0,420*v/peak)}" height="{200/n/len(series)}" fill="{color}"/>')
            elif kind=='stacked_bar':
                height=240*max(0,v)/peak;y=280-240*stacked[i]/peak-height;stacked[i]+=max(0,v)
                out.append(f'<rect x="{x-120/n}" y="{y}" width="{240/n}" height="{height}" fill="{color}"/>')
            elif kind in {'dot','lollipop'}:
                if kind=='lollipop':out.append(f'<line x1="{x}" x2="{x}" y1="280" y2="{y}" stroke="{color}"/>')
                out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
        if kind=='area':
            coords=' '.join(f'{x},{y}' for x,y in [(points[0][0],280),*points,(points[-1][0],280)])
            out.append(f'<polygon points="{coords}" fill="{color}" fill-opacity=".4" stroke="{color}"/>')
    return ''.join(out)+'</svg>'
