import json, sys
import mcp
from ui import *

left = brand() + divider_v() + F(
    "".join(F(T(s, 13, 600 if i == 0 else 500, C["ink"] if i == 0 else C["ink2"]), px=10, py=6, rounded=6,
              bg="#F2F4F7" if i == 0 else "#FFFFFF") for i, s in enumerate(["Queue", "Lint failures", "Exports"])),
    flex="row", gap=4)
right = (F(icon("search", 14, C["ink3"]) + T("Search doc_id, block id…", 13, 400, C["ink3"], grow=1) + kbd("/"),
           flex="row", items="center", gap=8, w=280, h=34, px=10, rounded=8, bg="#FFFFFF", stroke=C["line"])
         + btn("Start reviewing", "blue", "Enter", "play"))


def stat(label, value, sub, color=C["ink"], frac=None):
    bar = F(F(w=int(220 * frac), h=4, rounded=2, bg=color), w=220, h=4, rounded=2, bg="#EAECF0") if frac is not None else F(h=4)
    return F(T(label, 12, 500, C["ink2"]) + T(value, 26, 700, color) + bar + T(sub, 11, 400, C["ink3"]),
             flex="col", gap=8, w="fill", p=16, rounded=10, bg=C["panel"], stroke=C["line"])


stats = F(stat("Approved", "36 / 120", "30% of the batch", C["ok"], .30)
          + stat("Waiting for review", "71", "12 started, not finished", C["accent"], .59)
          + stat("Flagged for fix", "9", "sent back to the factory", C["warn"], .075)
          + stat("Rejected", "4", "C011 ×2 · C016 ×1 · visual ×1", C["err"], .033),
          flex="row", gap=12, w="fill")


def fchip(label, active=False, count=None):
    c = (F(T(str(count), 11, 600, C["ink2"]), px=6, rounded=999, bg="#EAECF0") if count is not None else "")
    return F(T(label, 12, 500, C["ink"] if active else C["ink2"]) + c + icon("chevron-down", 12, C["ink3"]),
             flex="row", items="center", gap=6, h=30, px=10, rounded=8, bg="#FFFFFF", stroke=C["accent"] if active else C["line"])


filters = F(F(fchip("doc_type: financial_report", True) + fchip("status: any") + fchip("lang: any") + fchip("layout: any")
              + fchip("lint: has warnings", False, 14) + fchip("reviewer: any"), flex="row", gap=8)
            + F(T("Sort", 12, 500, C["ink3"]) + fchip("lint issues first"), flex="row", items="center", gap=8),
            flex="row", justify="between", items="center", w="fill")

COLS = [("", 28), ("Document", 230), ("Type", 140), ("Lang", 70), ("Layout", 110), ("Pages", 120), ("Blocks", 70),
        ("Lint", 120), ("Status", 120), ("Reviewer", 120), ("Updated", 90)]
STATUS = {"approved": C["ok"], "in review": C["accent"], "todo": C["ink3"], "flagged": C["warn"], "rejected": C["err"]}
rows = [
    ("financial_report_000142", "financial_report", "vi", "multi_column", 7, 3, 96, ("C016", "W"), "in review", "you", "2m"),
    ("financial_report_000143", "financial_report", "en_vi_mixed", "mixed", 9, 0, 131, ("C015", "W"), "todo", "—", "1h"),
    ("financial_report_000139", "financial_report", "vi", "single_column", 6, 6, 74, None, "approved", "linh.t", "3h"),
    ("financial_report_000137", "financial_report", "en", "multi_column", 8, 8, 112, None, "approved", "you", "5h"),
    ("financial_report_000131", "financial_report", "vi", "mixed", 11, 4, 158, ("C011", "E"), "flagged", "minh.n", "1d"),
    ("financial_report_000129", "financial_report", "vi", "multi_column", 7, 0, 88, None, "todo", "—", "1d"),
    ("financial_report_000126", "financial_report", "en_vi_mixed", "single_column", 5, 5, 61, None, "approved", "linh.t", "1d"),
    ("financial_report_000121", "financial_report", "vi", "mixed", 10, 2, 140, ("C016", "W"), "rejected", "minh.n", "2d"),
    ("financial_report_000118", "financial_report", "en", "multi_column", 6, 0, 79, None, "todo", "—", "2d"),
]


def cell(content, w, grow=False):
    return F(content, w=w, flex="row", items="center", gap=6, h="fill") if not grow else F(content, grow=1, flex="row", items="center", gap=6, h="fill")


def pages_bar(n, done, w=80):
    seg = "".join(F(w="fill", grow=1, h=6, rounded=1, bg=C["ok"] if i < done else "#EAECF0") for i in range(n))
    return F(seg, flex="row", gap=2, w=w) + mono(f"{done}/{n}", 11, C["ink3"])


def row(r, i):
    doc, typ, lang, lay, n, done, nb, lint, st, who, upd = r
    lint_v = (F(icon("triangle-alert" if lint[1] == "W" else "octagon-x", 12, C["warn"] if lint[1] == "W" else C["err"]) + mono(lint[0], 11, C["ink"], 500),
                flex="row", items="center", gap=4) if lint else F(icon("circle-check", 12, C["ok"]) + T("clean", 11, 500, C["ink3"]), flex="row", items="center", gap=4))
    cells = [F(w=14, h=14, rounded=3, stroke="#D0D5DD", bg="#FFFFFF"), mono(doc, 12, C["ink"], 500), T(typ, 12, 400, C["ink2"]),
             mono(lang, 11, C["ink2"]), T(lay, 12, 400, C["ink2"]), pages_bar(n, done), mono(str(nb), 12, C["ink2"]),
             lint_v, chip(st, STATUS[st]), T(who, 12, 400, C["ink2"]), T(upd + " ago", 12, 400, C["ink3"])]
    return F("".join(cell(c, w) for c, (_, w) in zip(cells, COLS)), name=f"Row {doc}", flex="row", w="fill", h=44, px=16, gap=8,
             bg="#F5F8FF" if i == 0 else "#FFFFFF", stroke=C["line"], strokeWeights={"bottom": 1})


head = F("".join(cell(T(h.upper(), 10, 700, C["ink3"], letterSpacing=0.5), w) for h, w in COLS), flex="row", w="fill", h=36, px=16, gap=8,
         bg="#F9FAFB", stroke=C["line"], strokeWeights={"bottom": 1})
table = F(head + "".join(row(r, i) for i, r in enumerate(rows))
          + F(T("Showing 1–9 of 120", 12, 400, C["ink3"]) + F(icon("chevron-left", 14) + mono("1", 12, C["ink"], 600) + mono("2  3 … 14", 12, C["ink3"]) + icon("chevron-right", 14), flex="row", items="center", gap=10),
              flex="row", justify="between", items="center", w="fill", h=44, px=16),
          name="Document table", flex="col", w="fill", rounded=10, bg=C["panel"], stroke=C["line"], overflow="hidden")

body = F(F(T("Review queue", 22, 700) + T("Batch out/documents · dataset v0.3 · contract 0.2.0", 13, 400, C["ink3"]), flex="col", gap=4)
         + stats + filters + table, name="Body", flex="col", gap=16, w="fill", grow=1, px=28, py=24)
root = F(topbar(left, right) + body, name="01 · Queue", flex="col", w=1440, h=900, bg=C["bg"], overflow="hidden")

args = dict(jsx=root, x=0, y=1000)
if len(sys.argv) > 1:
    args = dict(jsx=root, replace_id=sys.argv[1])
print(json.dumps(mcp.call("render", **args))[:300])
