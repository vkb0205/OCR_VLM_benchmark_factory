"""Shared JSX helpers for the GT Review sketches."""
import json

C = dict(bg="#F4F5F7", panel="#FFFFFF", line="#E4E7EC", ink="#101828", ink2="#475467", ink3="#98A2B3",
         accent="#2E5BFF", ok="#12B76A", warn="#F79009", err="#F04438")
CAT = {"title": "#7C3AED", "section_header": "#A855F7", "text_block": "#2563EB", "table": "#059669",
       "caption_table": "#0D9488", "chart": "#EA580C", "caption_chart": "#F97316", "header": "#64748B",
       "footer": "#64748B", "page_number": "#64748B", "footnote": "#CA8A04"}


def tint(hex_, a, base="#FFFFFF"):
    """Opaque mix of hex_ over base at alpha a (keeps exports faithful)."""
    h = [int(hex_[i:i+2], 16) for i in (1, 3, 5)]; b = [int(base[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x*a + y*(1-a)):02X}" for x, y in zip(h, b))


def _props(kw):
    out = []
    for k, v in kw.items():
        out.append(f'{k}="{v}"' if isinstance(v, str) else f'{k}={{{json.dumps(v)}}}')
    return " ".join(out)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("{", "&#123;").replace("}", "&#125;")


def T(s, size=13, wt=400, color=C["ink"], font="Inter", **kw):
    return f'<Text size={{{size}}} weight={{{wt}}} color="{color}" font="{font}" {_props(kw)}>{esc(s)}</Text>'


def mono(s, size=12, color=C["ink2"], wt=400, **kw):
    return T(s, size, wt, color, "JetBrains Mono", **kw)


def icon(name, size=16, color=C["ink2"]):
    return f'<Icon name="lucide:{name}" size={{{size}}} color="{color}" />'


def F(children="", **kw):
    """Frame. Use _bg etc. not needed; pass props as kwargs."""
    return f'<Frame {_props(kw)}>{children}</Frame>'


def kbd(k):
    return F(mono(k, 11, C["ink2"], 500), px=6, py=2, rounded=4, bg="#F2F4F7", stroke=C["line"])


def btn(label, kind="ghost", key=None, ic=None):
    bg, fg, st = {"primary": (C["ok"], "#FFFFFF", C["ok"]), "danger": ("#FFFFFF", C["err"], "#FDA29B"),
                  "ghost": ("#FFFFFF", C["ink"], C["line"]), "blue": (C["accent"], "#FFFFFF", C["accent"])}[kind]
    inner = (icon(ic, 16, fg) if ic else "") + T(label, 13, 600, fg)
    if key:
        inner += F(mono(key, 10, fg, 500), px=5, py=1, rounded=4, bg=tint(fg, .2, bg) if kind in ("primary", "blue") else "#F2F4F7")
    return F(inner, name=f"Button/{label}", flex="row", items="center", gap=8, h=34, px=12, rounded=8, bg=bg, stroke=st)


def chip(label, color):
    return F(F(w=6, h=6, rounded=3, bg=color) + T(label, 11, 600, color),
             flex="row", items="center", gap=6, px=8, py=3, rounded=999, bg=tint(color, .1))


def divider_v(h=20):
    return F(w=1, h=h, bg=C["line"])


def topbar(left, right):
    return F(F(left, flex="row", items="center", gap=16) + F(right, flex="row", items="center", gap=12),
             name="Topbar", flex="row", items="center", justify="between", w="fill", h=56, px=20,
             bg=C["panel"], stroke=C["line"], strokeWeights={"bottom": 1})


def brand():
    return F(F(icon("scan-text", 15, "#FFFFFF"), w=26, h=26, rounded=7, bg=C["ink"], flex="row", items="center", justify="center")
             + T("GT Review", 14, 700), flex="row", items="center", gap=8)
