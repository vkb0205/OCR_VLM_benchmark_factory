"""Vietnamese statement numbers and total recomputation; no LLM-written total is trusted."""

import re


def format_vnd(value: int | None, lang="vi") -> str:
    if value is None or value == 0:
        return "-"
    if type(value) is not int:
        raise TypeError("Statement values must be integer VND")
    text = f"{abs(value):,}"
    if lang == "vi": text = text.replace(",", ".")
    return f"({text})" if value < 0 else text


def parse_vnd(text: str, lang="vi") -> int:
    text = text.strip()
    if lang == "en": text = text.replace(",", ".")
    if text in {"", "-"}:
        return 0
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})*|\d+)|\((?:\d{1,3}(?:\.\d{3})*|\d+)\)", text):
        raise ValueError(f"Invalid statement number: {text}")
    negative = text.startswith("(")
    value = int(text.strip("()").replace(".", ""))
    return -value if negative else value


def parse_formula(formula: str):
    """'30 = 20 + 21 - 22' -> ('30', [('20', 1), ('21', 1), ('22', -1)])"""
    if not re.fullmatch(r"\s*[0-9A-Za-z]+\s*=\s*[+-]?\s*[0-9A-Za-z]+(?:\s*[+-]\s*[0-9A-Za-z]+)*\s*", formula):
        raise ValueError(f"Invalid statement formula: {formula}")
    total, expression = (part.strip() for part in formula.split("="))
    terms = re.findall(r"([+-]?)\s*([0-9A-Za-z]+)", expression)
    return total, [(code, -1 if sign == "-" else 1) for sign, code in terms]


def solve(spec: dict, given: dict[str, list[int]]):
    """Return (values, included codes, adjustment log) for one statement.

    Totals whose terms include a written line are added and recomputed; each
    balance then moves its plug line so both sides are equal.
    """
    formulas = [parse_formula(f) for f in spec.get("formulas", [])]
    dependencies = dict(formulas)

    def has_leaf(code, seen=frozenset()):
        if code in seen:
            return False
        terms = dependencies.get(code)
        if terms is not None:
            return any(has_leaf(c, seen | {code}) for c, _ in terms)
        if code in given:
            return True
        # A balancing plug also receives values from the opposite side.
        return any(has_leaf(side, seen | {code}) for balance in spec.get("balances", [])
                   if balance["plug"] == code for side in balance["equal"])

    for total, _ in formulas:
        if total in given and not has_leaf(total):
            raise ValueError(f"Total {total} has no written leaf lines")
    included = set(given) | {b["plug"] for b in spec.get("balances", [])}
    included.update(code for b in spec.get("balances", []) for code in b["equal"])
    changed = True
    while changed:
        changed = False
        for total, terms in formulas:
            if total not in included and any(code in included for code, _ in terms):
                included.add(total)
                changed = True
    values = {code: list(given.get(code, [0, 0])) for code in included}
    log = []

    def recompute():
        for _ in range(len(formulas) + 1):
            before = dict(values)
            for total, terms in formulas:
                if total in included:
                    values[total] = [sum(sign * values.get(code, [0, 0])[p] for code, sign in terms) for p in (0, 1)]
            if values == before:
                return
        raise ValueError("Statement formulas did not converge; check for a circular dependency")

    recompute()
    for balance in spec.get("balances", []):
        left, right = balance["equal"]
        plug = balance["plug"]
        before = list(values[plug])
        for p in (0, 1):
            values[plug][p] += values[left][p] - values[right][p]
        recompute()
        if values[plug] != before:
            log.append({"code": plug, "written": before, "printed": values[plug], "reason": f"balance {left} = {right}"})
    for balance in spec.get("balances", []):
        left, right = balance["equal"]
        if values[left] != values[right]:
            raise ValueError(f"Balance {left} = {right} failed after plug")
    totals = {total for total, _ in formulas}
    for code in given:
        if code in totals and values[code] != given[code]:
            log.append({"code": code, "written": list(given[code]), "printed": list(values[code]),
                        "reason": "total recomputed"})
    return values, included, log
