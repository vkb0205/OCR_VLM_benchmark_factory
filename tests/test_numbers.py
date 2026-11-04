"""Statement number formatting and total recomputation."""

import pytest

from factory.content.numbers import format_vnd, parse_vnd, solve
from factory.content.config import load_config


def test_format_round_trip():
    for value in [0, 7, 1_234_567_890, -12_345_678]:
        assert parse_vnd(format_vnd(value)) == value
    assert format_vnd(-1_234) == "(1.234)" and format_vnd(0) == "-"
    with pytest.raises(TypeError):
        format_vnd(1.5)


def test_totals_recomputed_and_balanced():
    spec = load_config().documents['financial_report'].statements["B01"]
    given = {"111": [100, 90], "141": [50, 40], "222": [300, 280], "223": [-60, -40],
             "411": [200, 200], "311": [80, 70], "421b": [30, 25], "270": [1, 1]}
    values, included, log = solve(spec, given)
    assert values["270"] == values["440"] == [390, 370]
    assert values["110"] == [100, 90] and values["221"] == [240, 240]
    assert {"100", "110", "200", "270", "421", "421a", "440"} <= included
    assert {entry["code"] for entry in log} == {"270", "421a"}


def test_income_statement_formulas():
    spec = load_config().documents['financial_report'].statements["B02"]
    values, _, _ = solve(spec, {"01": [1000, 900], "02": [10, 0], "11": [700, 600], "25": [50, 40],
                                "26": [40, 30], "51": [40, 46], "52": [0, 0]})
    assert values["10"] == [990, 900] and values["20"] == [290, 300]
    assert values["50"] == [200, 230] and values["60"] == [160, 184]


def test_formula_parser_and_empty_balance():
    from factory.content.numbers import parse_formula
    assert parse_formula('30 = 20 + 21 - 22') == ('30', [('20', 1), ('21', 1), ('22', -1)])
    for formula in ('30 = 20 * 21', '30 =', '30 = 20 +', '30 = 20 garbage'):
        with pytest.raises(ValueError, match='Invalid statement formula'):
            parse_formula(formula)
    spec = load_config().documents['financial_report'].statements['B01']
    values, _, _ = solve(spec, {})
    assert values['270'] == values['440'] == [0, 0]


def test_overwrite_log_records_final_balanced_values():
    spec = load_config().documents['financial_report'].statements['B01']
    given = {'111': [100, 80], '440': [1, 1]}
    values, _, log = solve(spec, given)
    overwritten = next(entry for entry in log if entry['code'] == '440')
    assert overwritten['printed'] == values['440'] == [100, 80]
    assert given == {'111': [100, 80], '440': [1, 1]}
