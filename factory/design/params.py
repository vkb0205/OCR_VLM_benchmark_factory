"""Hard design parameters drawn by code from the design seed.

The model is told to use them exactly; code also applies the ones it can enforce itself (page sizes,
CSS variables, fonts, chart forms and colors). This spreads documents over the whole design space
instead of the few looks a model drifts to on its own.
"""
import colorsys
import random

FONTS = {
    "Be Vietnam Pro": "BeVietnamPro-Regular.ttf",
    "Inter": "Inter-VF.ttf",
    "Lora": "Lora-VF.ttf",
    "Merriweather": "Merriweather-VF.ttf",
    "Montserrat": "Montserrat-VF.ttf",
    "Noto Sans": "NotoSans-VF.ttf",
    "Noto Serif": "NotoSerif-VF.ttf",
    "Source Serif 4": "SourceSerif4-VF.ttf",
}

HEADER_POSITIONS = ["top, full width", "top, right-aligned block", "bottom, above the footer",
                    "left margin, rotated vertical", "right margin, rotated vertical", "top, inside a colour band"]
COVERS = ["centred stack", "left-aligned stack", "split: colour panel on one side, text on the other",
          "bottom-heavy: title block in the lower third", "full-bleed accent background with light text",
          "framed: thin border box around the content", "top band with logo, text below",
          "diagonal or offset blocks of colour behind the title area"]
SIZE_PLANS = {
    "portrait A4 throughout": lambda role: "a4",
    "portrait US letter throughout": lambda role: "letter",
    "landscape statements and notes, portrait cover and text pages":
        lambda role: "a4_landscape" if role in {"B01", "B02", "B03", "notes", "key_figures"} else "a4",
    "landscape A4 throughout": lambda role: "a4_landscape",
    "legal-size statements, A4 elsewhere":
        lambda role: "legal" if role in {"B01", "B02", "B03"} else "a4",
    "landscape letter for data pages, portrait letter for text":
        lambda role: "letter_landscape" if role in {"B01", "B02", "B03", "key_figures"} else "letter",
}
# Table style -> the ruling it must draw, which is also the frame_type label in the ground truth.
TABLE_STYLES = {
    "full grid: every cell boxed": "full_line",
    "ruled rows: horizontal lines between rows, no vertical lines": "less_line",
    "minimal: one rule under the header and one at the bottom": "fewer_line",
    "zebra: alternating row shading, no lines at all": "wireless_line",
    "dark header band, no lines in the body": "wireless_line",
    "dense: small type, thin horizontal rules": "less_line",
}
DECORATIONS = ["none", "a thin accent stripe along one page edge", "solid colour band at the top or bottom edge",
               "small geometric blocks in two corners", "double rules framing the page margins",
               "a large pale circle or arc partly off the page edge, in the margin",
               "a vertical colour band in the outer margin"]
BAR_FORMS = ["bar", "hbar", "grouped_column", "lollipop", "dot", "stacked_bar"]
LINE_FORMS = ["line", "area", "line", "dot"]


def _hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h % 1, s, v)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def draw_params(seed: int) -> dict:
    rng = random.Random(seed * 7919 + 17)
    hue = rng.randrange(360)
    heading, body = rng.sample(list(FONTS), 2)
    second = (hue + rng.choice([150, 180, 210])) % 360
    table_style = rng.choice(list(TABLE_STYLES))
    plan = rng.choice(list(SIZE_PLANS))
    return {
        "accent_hue": hue,
        "accent": _hex(hue / 360, rng.uniform(.55, .85), rng.uniform(.45, .7)),
        "paper": rng.choice(["#ffffff", "#ffffff", _hex(hue / 360, .04, .99), _hex(rng.random(), .03, .97)]),
        "heading_font": heading,
        "body_font": body,
        "body_size_pt": rng.choice([8.5, 9, 9.5, 10, 10.5, 11]),
        "margin_mm": rng.choice([10, 13, 16, 19, 22, 26]),
        "header_position": rng.choice(HEADER_POSITIONS),
        "prose_columns": rng.choice([1, 1, 2, 2, 3]),
        "cover": rng.choice(COVERS),
        "size_plan": plan,
        "table_style": table_style,
        "frame": TABLE_STYLES[table_style],
        "decoration": rng.choice(DECORATIONS),
        "chart_forms": {"bar": rng.choice(BAR_FORMS), "line": rng.choice(LINE_FORMS), "donut": "donut"},
        "chart_colors": [_hex(hue / 360, .7, .55), _hex(second / 360, .5, .8), "#7a7a7a"],
    }


def shared_traits(params: dict, other: dict) -> list[str]:
    """Code-drawn traits two designs share; two or more makes them near-copies (design/checks.py)."""
    shared = []
    if params.get("size_plan") and params.get("size_plan") == other.get("size_plan"):
        shared.append("same orientation option")
    if (params.get("heading_font"), params.get("body_font")) == (other.get("heading_font"), other.get("body_font")):
        shared.append("same heading/body font pairing")
    if "accent_hue" in params and "accent_hue" in other:
        gap = abs(params["accent_hue"] - other["accent_hue"]) % 360
        if min(gap, 360 - gap) < 25:
            shared.append("accent hue within 25 degrees")
    return shared


def draw_distinct_params(seed: int, recent: list[dict]) -> dict:
    """The seed's parameters, re-drawn deterministically until they share at most one trait with each recent design.

    Code owns these traits, so code (not the design agent) guarantees they differ."""
    recent = [r for r in recent if isinstance(r, dict) and r]
    for attempt in range(60):
        params = draw_params(seed if attempt == 0 else seed * 1009 + attempt)
        if all(len(shared_traits(params, other)) < 2 for other in recent):
            return params
    return draw_params(seed)


def page_size(params: dict, role: str) -> str:
    return SIZE_PLANS[params["size_plan"]](role)


def css_variables(params: dict) -> str:
    """Fonts and variables the model's CSS builds on."""
    faces = "".join(
        f'@font-face{{font-family:"{name}";src:url("assets/fonts/{FONTS[name]}")}}'
        for name in (params["heading_font"], params["body_font"])
    )
    return (faces + ":root{"
            f"--accent:{params['accent']};--paper:{params['paper']};"
            f"--font-head:\"{params['heading_font']}\",serif;--font-body:\"{params['body_font']}\",sans-serif;"
            f"--base-size:{params['body_size_pt']}pt;--margin:{params['margin_mm']}mm"
            "}")


# The drawn running-header position, built by code on top of the base page frame (skeleton.BASE_CSS).
# .page.page outranks the base rules, including :has(>.page-number) ones.
_M = "var(--margin,15mm)"
HEADER_FRAMES = {
    "top, full width": "",
    "top, right-aligned block": "section.page.page>header{text-align:right!important}",
    "top, inside a colour band": "",
    "bottom, above the footer": (
        f"section.page.page>header{{top:auto!important;bottom:calc({_M} + 7mm)!important}}"
        f"section.page.page:has(>header)>main{{top:{_M}!important;bottom:calc({_M} + 21mm)!important}}"),
    "left margin, rotated vertical": (
        f"section.page.page>header{{top:{_M}!important;bottom:{_M}!important;left:calc({_M} / 2 - 3mm)!important;"
        "right:auto!important;width:auto!important;writing-mode:vertical-rl!important;"
        "transform:rotate(180deg)!important;text-align:left!important;white-space:nowrap!important}"
        f"section.page.page:has(>header)>main{{top:{_M}!important}}"),
    "right margin, rotated vertical": (
        f"section.page.page>header{{top:{_M}!important;bottom:{_M}!important;left:auto!important;"
        f"right:calc({_M} / 2 - 3mm)!important;width:auto!important;writing-mode:vertical-rl!important;"
        "text-align:left!important;white-space:nowrap!important}"
        f"section.page.page:has(>header)>main{{top:{_M}!important}}"),
}


def frame_css(params: dict) -> str:
    return HEADER_FRAMES.get(params.get("header_position", ""), "")


def prompt_lines(params: dict) -> list[str]:
    return [
        "Required parameters (drawn by code; follow them exactly):",
        f"- accent colour {params['accent']} (hue {params['accent_hue']}°), paper {params['paper']}: "
        "use var(--accent) and var(--paper); add your own tints/shades of the accent and a dark ink.",
        f"- fonts: headings {params['heading_font']} = var(--font-head), body {params['body_font']} = var(--font-body) "
        "(already loaded; no other fonts).",
        f"- body text {params['body_size_pt']} pt = var(--base-size); page margins about {params['margin_mm']} mm.",
        f"- running header position: {params['header_position']} (code places it; you style it).",
        f"- board report text: {params['prose_columns']} column(s) (CSS columns or grid). Notes, auditor "
        "report, statements and KPIs flow across pages, so lay them out in one column (no column-count there).",
        f"- cover composition: {params['cover']}.",
        f"- sheet sizes: {params['size_plan']} (set by code).",
        f"- every table: {params['table_style']}.",
        f"- decoration: {params['decoration']}.",
    ]
