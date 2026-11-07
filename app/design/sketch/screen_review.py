import json, sys
import mcp
from ui import *

# ---------- top bar
left = brand() + divider_v() + F(
    T("financial_report", 13, 500, C["ink2"]) + icon("chevron-right", 14, C["ink3"])
    + mono("financial_report_000142", 13, C["ink"], 600) + chip("in review", C["warn"]),
    flex="row", items="center", gap=6)
right = (F(icon("chevron-left", 16) + T("Doc 37 of 120", 12, 500, C["ink2"])
           + F(F(w=37, h=6, rounded=3, bg=C["accent"]), w=120, h=6, rounded=3, bg="#EAECF0")
           + icon("chevron-right", 16), flex="row", items="center", gap=8)
         + divider_v() + btn("Reject", "danger", "R", "x") + btn("Flag for fix", "ghost", "F", "flag")
         + btn("Approve page", "primary", "A", "check"))

# ---------- page rail
pages = [("cover", "ok"), ("B01", "ok"), ("B02", "cur"), ("B02", "todo"), ("notes", "todo"), ("notes", "warn"), ("chart", "todo")]


def thumb(i, role, st):
    cur = st == "cur"
    dot = {"ok": C["ok"], "cur": C["accent"], "todo": "#D0D5DD", "warn": C["warn"]}[st]
    bars = "".join(F(w=w, h=3, rounded=1, bg="#D0D5DD") for w in (40, 64, 58, 64, 30, 64, 52))
    return F(F(bars, flex="col", gap=5, w=72, h=100, p=7, bg="#FFFFFF", rounded=3, stroke=C["line"])
             + F(mono(f"p{i:03d}", 11, C["ink"] if cur else C["ink2"], 600 if cur else 400) + F(w=7, h=7, rounded=4, bg=dot),
                 flex="row", items="center", justify="between", w=72)
             + T(role, 10, 400, C["ink3"]),
             name=f"Thumb p{i:03d}", flex="col", gap=5, p=6, rounded=8,
             bg="#EEF2FF" if cur else "#FFFFFF00", stroke=C["accent"] if cur else "#FFFFFF00", strokeWidth=1.5)


rail = F(F(T("PAGES", 10, 700, C["ink3"], letterSpacing=0.6) + T("2/7", 10, 600, C["ink3"]), flex="row", justify="between", w=72, pb=4)
         + "".join(thumb(i + 1, r, s) for i, (r, s) in enumerate(pages)),
         name="Pages", flex="col", items="center", gap=2, w=100, h="fill", py=12, bg=C["panel"],
         stroke=C["line"], strokeWeights={"right": 1}, overflow="hidden")

# ---------- the page with overlays
PW, PH = 480, 679
blocks = [  # id, cat, ro, x, y, w, h, kind
    ("pf_p003_header", "header", 1, 34, 24, 412, 12, "hdr"),
    ("b14", "section_header", 2, 34, 58, 290, 20, "h2"),
    ("b15", "text_block", 3, 34, 92, 412, 52, "para"),
    ("b16", "caption_table", 4, 34, 160, 250, 12, "cap"),
    ("b17", "table", 5, 34, 182, 412, 200, "table"),
    ("b18", "text_block", 6, 34, 400, 198, 92, "para"),
    ("b19", "chart", 7, 248, 400, 198, 140, "chart"),
    ("b20", "caption_chart", 8, 248, 548, 198, 12, "cap"),
    ("b18:2", "text_block", 9, 34, 500, 198, 62, "para"),
    ("b21", "footnote", 10, 34, 584, 412, 26, "para"),
    ("pf_p003_footer", "footer", 11, 34, 644, 290, 12, "hdr"),
    ("pf_p003_pn", "page_number", 12, 418, 644, 28, 12, "hdr"),
]
SEL = "b17"


def ink(kind, w, h):
    if kind == "para":
        n = max(1, (h + 2) // 10)
        return F("".join(F(w=w if i < n - 1 else int(w * .6), h=4, rounded=1, bg="#B9C0CC") for i in range(n)), flex="col", gap=5, w=w, pt=3)
    if kind == "h2":
        return F(F(w=int(w * .8), h=11, rounded=2, bg="#344054"), pt=4)
    if kind in ("cap", "hdr"):
        return F(F(w=int(w * .7), h=5, rounded=1, bg="#98A2B3"), pt=4)
    if kind == "table":
        cws = (168, 80, 82, 82)
        rows = ""
        for r in range(10):
            cells = "".join(F(F(w=int(cw * (.75 if c == 0 else .45)), h=4, rounded=1, bg="#475467" if r == 0 else "#B9C0CC"),
                              w=cw, h=19.5, px=6, flex="row", items="center", justify="end" if c else "start")
                            for c, cw in enumerate(cws))
            rows += F(cells, flex="row", w=w, bg="#F2F4F7" if r == 0 else "#FFFFFF00", stroke="#98A2B3", strokeWeights={"bottom": 1.5 if r == 0 else .5})
        return F(rows, flex="col", w=w, stroke="#475467", strokeWeights={"top": 1.5})
    if kind == "chart":
        bars = "".join(F(w=18, h=hh, bg=c) for hh, c in ((48, "#94A3B8"), (66, "#64748B"), (60, "#94A3B8"), (90, "#64748B"), (76, "#94A3B8"), (106, "#334155")))
        return F(bars, flex="row", items="end", gap=11, w=w, h=h, px=14, pb=8, stroke="#98A2B3", strokeWeights={"bottom": 1, "left": 1})


ink_layer = "".join(F(ink(k, w, h), position="absolute", x=x, y=y, w=w, h=h) for _, _, _, x, y, w, h, k in blocks)


def overlay(bid, cat, ro, x, y, w, h, _):
    col, sel, p = CAT[cat], bid == SEL, 3
    tag = F(mono(f"{bid} · table · 1/2", 10, "#FFFFFF", 600), position="absolute", x=w + 2 * p - 128, y=-20, h=18, px=6,
            rounded=3, bg=col, flex="row", items="center") if sel else ""
    badge = F(T(str(ro), 9, 700, "#FFFFFF"), position="absolute", x=-9, y=-9, w=18, h=18, rounded=9, bg=col,
              flex="row", items="center", justify="center", stroke="#FFFFFF", strokeWidth=1.5)
    return F(badge + tag, name=f"bbox {bid}", position="absolute", x=x - p, y=y - p, w=w + 2 * p, h=h + 2 * p,
             bg=tint(col, .16 if sel else .06), opacity=.9, stroke=col, strokeWidth=2 if sel else 1, rounded=2)


pts = [(x + w / 2, y + h / 2) for _, _, _, x, y, w, h, _ in sorted(blocks, key=lambda b: b[2])]
d = "M " + " L ".join(f"{a:.0f} {b:.0f}" for a, b in pts)
ro_svg = (f'<svg name="Reading order path" viewBox="0 0 {PW} {PH}" size={{{PW}}} position="absolute" x={{0}} y={{0}}>'
          f'<path d="{d}" stroke="#2E5BFF" stroke-width="1.25" fill="none" stroke-dasharray="3 3" opacity="0.6" /></svg>')
warn = F(icon("triangle-alert", 11, "#FFFFFF") + mono("C016 overlap", 10, "#FFFFFF", 600), position="absolute", x=150, y=482,
         flex="row", items="center", gap=4, px=6, py=2, rounded=4, bg=C["warn"])
page = F(ink_layer + ro_svg + "".join(overlay(*b) for b in blocks) + warn, name="Page p003 (image + overlays)",
         w=PW, h=PH, bg="#FFFFFF", shadow="0 1 3 #1018281A, 0 8 24 #10182814")


def seg(items, active):
    return F("".join(F(T(s, 12, 600 if i == active else 500, C["ink"] if i == active else C["ink2"]), px=10, py=4, rounded=6,
                       bg="#FFFFFF" if i == active else "#FFFFFF00", shadow="0 1 2 #1018281A" if i == active else "0 0 0 #0000")
                     for i, s in enumerate(items)), flex="row", p=2, gap=2, rounded=8, bg="#EAECF0")


def toggle(label, on, key):
    return F(icon("eye" if on else "eye-off", 14, C["accent"] if on else C["ink3"]) + T(label, 12, 500, C["accent"] if on else C["ink2"]) + kbd(key),
             flex="row", items="center", gap=6, px=8, py=4, rounded=6, bg="#EEF2FF" if on else "#FFFFFF00")


toolbar = F(seg(["Image", "HTML", "Side by side"], 0)
            + F(toggle("Boxes", True, "B") + toggle("Order", True, "O") + toggle("Ignored", False, "I"), flex="row", items="center", gap=4)
            + F(icon("minus", 14) + mono("100%", 12, C["ink"], 500) + icon("plus", 14), flex="row", items="center", gap=8),
            name="Canvas toolbar", flex="row", items="center", justify="between", w="fill", h=48, px=16,
            bg=C["panel"], stroke=C["line"], strokeWeights={"bottom": 1})
legend = F("".join(chip(c, CAT[c]) for c in ("section_header", "text_block", "table", "caption_table", "chart", "footnote", "header")),
           flex="row", items="center", gap=8, wrap=True)
canvas = F(toolbar + F(page + legend, name="Viewport", flex="col", items="center", justify="center", gap=14, w="fill", grow=1, bg=C["bg"], overflow="hidden"),
           name="Canvas", flex="col", grow=1, h="fill")


# ---------- inspector
def field(label, value, dd=False):
    return F(T(label, 11, 500, C["ink3"]) + F(mono(value, 12, C["ink"], 500) + (icon("chevrons-up-down", 12, C["ink3"]) if dd else ""),
             flex="row", items="center", justify="between", w="fill", h=30, px=10, rounded=6, bg="#FFFFFF", stroke=C["line"]),
             flex="col", gap=4, w="fill")


def verdict(label, key, sel=False, col=C["ink"]):
    return F(T(label, 12, 600 if sel else 500, col if sel else C["ink"]) + kbd(key), flex="row", items="center", justify="between",
             w="fill", h=32, px=10, rounded=6, bg=tint(col, .1) if sel else "#FFFFFF", stroke=col if sel else C["line"])


def blockrow(ro, bid, cat, sel=False, flag=False, done=False):
    mark = icon("triangle-alert", 12, C["warn"]) if flag else (icon("check", 12, C["ok"]) if done else F(w=12, h=12))
    return F(icon("grip-vertical", 12, "#D0D5DD") + mono(f"{ro:>2}", 11, C["ink3"]) + F(w=8, h=8, rounded=2, bg=CAT[cat])
             + mono(bid, 11, C["ink"], 500, w=110) + T(cat, 11, 400, C["ink2"], grow=1) + mark,
             flex="row", items="center", gap=8, w="fill", h=26, px=8, rounded=6, bg="#EEF2FF" if sel else "#FFFFFF00")


tabs = F(F(T("Block", 13, 600, C["accent"]) + F(w="fill", h=2, bg=C["accent"]), flex="col", gap=10)
         + F(T("Page", 13, 500, C["ink2"]), pb=12)
         + F(T("Lint", 13, 500, C["ink2"]) + F(T("2", 11, 700, "#B54708"), px=6, py=1, rounded=999, bg="#FEF0C7"), pb=12, flex="row", gap=6, items="center")
         + F(T("Document", 13, 500, C["ink2"]), pb=12),
         flex="row", items="end", gap=18, w="fill", h=44, px=16, stroke=C["line"], strokeWeights={"bottom": 1})
gt = ('<table><tr><td>Chỉ tiêu</td><td>Mã số</td><td>31/12/2025</td><td>01/01/2025</td></tr>'
      '<tr><td>Tiền và các khoản tương đương tiền</td><td>110</td><td>1.284.556</td><td>1.102.871</td></tr>…')
details = F(
    F(F(F(w=10, h=10, rounded=2, bg=CAT["table"]) + mono("b17", 15, C["ink"], 700) + T("Bảng cân đối kế toán", 12, 400, C["ink3"]),
        flex="row", items="center", gap=8)
      + F(icon("chevron-up", 16, C["ink3"]) + icon("chevron-down", 16, C["ink3"]), flex="row", gap=6), flex="row", items="center", justify="between", w="fill")
    + F(field("Category", "table", True) + field("Reading order", "5 / 12") + field("Part", "1 / 2") + field("Language", "vi", True)
        + field("frame_type", "fewer_line", True) + field("Caption", "b16"), grid=True, columns="1fr 1fr", gap=10, w="fill")
    + F(F(T("Ground truth · minified HTML", 11, 500, C["ink3"]) + F(icon("pencil", 12, C["accent"]) + T("Edit", 11, 600, C["accent"]), flex="row", gap=4, items="center"),
          flex="row", justify="between", w="fill")
        + F(mono(gt, 11, C["ink2"], w="fill", lineHeight=17), w="fill", h=88, p=10, rounded=6, bg="#F9FAFB", stroke=C["line"], overflow="hidden")
        + F(icon("circle-check", 13, C["ok"]) + T("C013 matches DocIR · body rows 1–9 of 18", 11, 500, C["ink2"]), flex="row", items="center", gap=6),
        flex="col", gap=6, w="fill")
    + F(T("Verdict", 11, 500, C["ink3"])
        + F(verdict("Correct", "1", True, C["ok"]) + verdict("Box is off", "2") + verdict("Text is wrong", "3")
            + verdict("Wrong category", "4") + verdict("Wrong order", "5") + verdict("Should be ignored", "6"),
            grid=True, columns="1fr 1fr", gap=6, w="fill"),
        flex="col", gap=6, w="fill"),
    name="Block details", flex="col", gap=14, w="fill", p=16)
blist = F(F(T("READING ORDER", 10, 700, C["ink3"], letterSpacing=0.6) + T("drag to reorder", 10, 400, C["ink3"]), flex="row", justify="between", w="fill", px=8, pb=4)
          + "".join(blockrow(ro, b, c, b == SEL, flag=b in ("b18:2", "b19"), done=ro < 5) for b, c, ro, *_ in blocks),
          name="Block list", flex="col", gap=1, w="fill", grow=1, px=8, py=12, overflow="hidden")
insp = F(tabs + details + F(w="fill", h=1, bg=C["line"]) + blist, name="Inspector", flex="col", w=380, h="fill",
         bg=C["panel"], stroke=C["line"], strokeWeights={"left": 1})

status = F(F("".join(F(kbd(k) + T(v, 11, 400, C["ink2"]), flex="row", items="center", gap=6)
                     for k, v in (("Tab", "next block"), ("1–6", "verdict"), ("Shift+drag", "redraw box"), ("J / K", "page"))), flex="row", items="center", gap=14)
           + F(mono("contract 0.2.0 · taxonomy 0.1.0 · 200 dpi", 11, C["ink3"]) + F(F(w=6, h=6, rounded=3, bg=C["ok"]) + T("Saved", 11, 500, C["ink2"]), flex="row", items="center", gap=6),
               flex="row", items="center", gap=14),
           name="Statusbar", flex="row", items="center", justify="between", w="fill", h=30, px=16, bg=C["panel"], stroke=C["line"], strokeWeights={"top": 1})

root = F(topbar(left, right) + F(rail + canvas + insp, flex="row", w="fill", grow=1) + status,
         name="02 · Page review", flex="col", w=1440, h=900, bg=C["bg"], overflow="hidden")

args = dict(jsx=root, x=0, y=0)
if len(sys.argv) > 1:
    args["replace_id"] = sys.argv[1]
print(json.dumps(mcp.call("render", **args))[:800])
