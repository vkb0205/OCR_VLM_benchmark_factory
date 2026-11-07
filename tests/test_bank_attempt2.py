"""Replay all available attempt-2 cache replies and final checkpoints, without HTTP."""
import asyncio
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from factory.content import bank
from factory.content.article import check_article, check_chart, normalize_chart
from factory.content.config import load_config
from factory.content.schema import validate_content
from factory.llm.client import Endpoint, LLMResult, parse_json

FIXTURES = Path(__file__).parent / 'fixtures/bank_replays/attempt2'
ROWS = json.loads((FIXTURES / 'replies.json').read_text(encoding='utf-8'))
FIELDS = ['materials modelling', 'signal processing', 'robotics', 'hydrology', 'linguistics', 'ecology']
CHECKPOINTS = {i: json.loads((FIXTURES / f'paper_{i:02}.groups.json').read_text(encoding='utf-8')) for i in range(1, 7)}


def variables(index):
    return {'lang': 'vi' if index % 2 else 'en', 'field': FIELDS[index-1],
            'paper_length': ['short', 'medium', 'long'][(index-1) % 3],
            'citation_style': 'numeric' if ((index-1)//2) % 2 == 0 else 'author_year',
            'element_plan': bank.draw_paper_plan(index-1, FIELDS[index-1])}


def router_stub(monkeypatch, generate):
    class Router:
        def __init__(self, **kwargs):
            pass
        def endpoint(self, agent):
            return Endpoint(name='luna', api='openai', model='gpt-6-luna',
                            api_key_env='unused', params={'reasoning_effort': 'medium'})
    Router.generate = generate
    monkeypatch.setattr(bank, 'Router', Router)


def prepare(tmp_path, count):
    for i in range(1, count+1):
        (tmp_path / f'.paper_{i:02}.groups.json').write_text(json.dumps(CHECKPOINTS[i]), encoding='utf-8')


@pytest.mark.parametrize('row', ROWS, ids=[f"paper{r['call']['paper']}-{r['call']['group']}-{i}" for i,r in enumerate(ROWS)])
def test_every_cached_reply_through_bank_pipeline(row, tmp_path, monkeypatch):
    index, name = row['call']['paper'], row['call']['group']
    v = variables(index)
    groups = deepcopy(CHECKPOINTS[index])
    data = parse_json(row['result']['text'], bank.GroupReply).data
    # Calculate the next action using real group and complete-paper validators.
    expected_error = None
    try:
        groups[name] = bank.clean_group(name, data, v['element_plan'])
    except (ValueError, KeyError, TypeError) as exc:
        expected_owner, expected_error = name, str(exc)
    else:
        values = bank.assemble(groups)
        try:
            bank.validate_paper({'variables': v, 'values': values})
        except (ValueError, KeyError, TypeError) as exc:
            expected_owner, expected_error = bank.repair_owner(exc, values), str(exc)
            if 'element ' in expected_error and any(f'({kind})' in expected_error for kind in ('chart','figure')):
                assert expected_owner == 'charts_figures'
    prepare(tmp_path, index)
    checkpoint = deepcopy(CHECKPOINTS[index])
    del checkpoint[name]
    (tmp_path / f'.paper_{index:02}.groups.json').write_text(json.dumps(checkpoint), encoding='utf-8')
    calls = []
    original_prompt = bank.group_prompt
    current = None
    def prompt(group, vars, accepted):
        nonlocal current
        current = (FIELDS.index(vars['field'])+1, group)
        return original_prompt(group, vars, accepted)
    monkeypatch.setattr(bank, 'group_prompt', prompt)
    delivered = False
    async def generate(self, agent, messages, **kwargs):
        nonlocal delivered
        paper, group = current
        if paper == index:
            calls.append((group, deepcopy(messages), kwargs))
            if not delivered:
                delivered = True
                assert group == name
                return LLMResult.model_validate(row['result'])
        raise RuntimeError('offline: next correctly routed repair captured')
    router_stub(monkeypatch, generate)
    asyncio.run(bank.build_bank(index, tmp_path, jobs=1))
    assert delivered
    if expected_error is None:
        assert (tmp_path / f'paper_{index:02}.json').exists()
        assert len(calls) == 1
    else:
        assert len(calls) == 2
        assert calls[1][0] == expected_owner
        assert expected_error in calls[1][1][-1]['content']
        assert calls[1][2]['use_cache'] is False
        assert 'Current group:' in calls[1][1][-1]['content']


def test_all_six_final_checkpoints_get_owned_repairs(tmp_path, monkeypatch):
    prepare(tmp_path, 6)
    owners = []
    original_prompt = bank.group_prompt
    def prompt(name, vars, groups):
        owners.append((FIELDS.index(vars['field'])+1, name))
        return original_prompt(name, vars, groups)
    monkeypatch.setattr(bank, 'group_prompt', prompt)
    async def generate(self, agent, messages, **kwargs):
        assert kwargs['use_cache'] is False
        assert 'body:' in messages[-1]['content']
        raise RuntimeError('offline correctly routed repair')
    router_stub(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(6, tmp_path, jobs=1)) == 1
    assert owners == [(i, 'charts_figures') for i in range(1, 7)]
    record = json.loads((tmp_path / 'bank_run.json').read_text(encoding='utf-8'))
    assert record['status'] == 'FAIL'
    assert len(record['failures']) == 6
    assert [row['group'] for row in record['errors']] == ['charts_figures'] * 6


@pytest.mark.parametrize('kind,element,owner', [
    ('chart', {'id':'fig:c','chart_type':'bar','labels':['a','b'], 'series':[{'name':'n','values':[1,2]}]}, 'charts_figures'),
    ('figure', {'id':'fig:f','figure_type':'block_diagram','description':'Diagram','labels':['a','b','c']}, 'charts_figures'),
    ('table', {'id':'tab:t','header':[['a','b']],'rows':[['1','2'],['3','4']]}, 'tables'),
    ('code', {'id':'alg:a','lines':['a']}, 'code'),
    ('equation', {'id':'eq:e','latex':''}, 'formulas'),
])
def test_schema_element_errors_always_route_by_type(kind, element, owner):
    v = variables(1)
    groups = {k: bank.clean_group(k, deepcopy(x), v['element_plan']) for k,x in CHECKPOINTS[1].items()}
    values = bank.assemble(groups)
    values['body'] = [{'type':kind, **element}]
    config = load_config().documents['academic_paper'].for_lang(v['lang'])
    with pytest.raises(ValueError) as caught:
        validate_content(config, values, lang=v['lang'], variables=v)
    error = str(caught.value)
    assert f'element 1 ({kind})' in error
    if kind in {'chart','figure','table'}:
        assert 'caption' in error
    # Deliberately conflicting element index: explicit error type wins.
    assert bank.repair_owner(caught.value, {'body':[{'type':'paragraph'}]}) == owner


def test_route_by_element_id():
    assert bank.repair_owner('invalid data for fig:results', {'body':[{'type':'chart','id':'fig:results'}]}) == 'charts_figures'
    assert bank.repair_owner('invalid tab:other', {'body':[{'type':'table','id':'tab:one'}]}) == 'body'


def chart(**changes):
    return {'type':'chart','id':'fig:chart','caption':'Measurements','chart_type':'line',
            'labels':['a','b','c'], 'series':[{'name':'n','values':['1.5','2','3'],'errors':['0.1','0.2','0.3']}], **changes}


def test_chart_numeric_strings_and_mismatched_errors():
    original = chart(series=[{'name':'n','values':['1.5','2','3'],'errors':['0.1']}])
    before = deepcopy(original)
    result = check_chart(original, str, 'element 1 (chart)')
    assert result['series'][0]['values'] == [1.5,2,3]
    assert 'errors' not in result['series'][0]
    assert original == before


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), 'NaN'])
def test_nonfinite_categories_removed_across_all_series(invalid):
    original = chart(series=[{'name':'n','values':[1,invalid,3],'errors':[0.1,0.2,0.3]},
                            {'name':'m','values':[4,5,6],'errors':[0.4,0.5,0.6]}])
    result = check_chart(original, str, 'element 1 (chart)')
    assert result['labels'] == ['a','c']
    assert result['series'][0]['values'] == [1,3]
    assert result['series'][1]['values'] == [4,6]
    assert result['series'][1]['errors'] == [0.4,0.6]


def test_nan_uncertainty_drops_only_errorbars():
    result = check_chart(chart(series=[{'name':'n','values':[1,2,3],'errors':[0.1,'NaN',0.3]}]), str, 'chart')
    assert result['series'][0]['values'] == [1,2,3]
    assert 'errors' not in result['series'][0]


def test_invalid_measurements_are_not_fabricated_or_misaligned():
    with pytest.raises(ValueError, match='finite numbers'):
        check_chart(chart(series=[{'name':'n','values':[1,'unknown',3]}]), str, 'chart')
    with pytest.raises(ValueError, match='one value per label'):
        check_chart(chart(series=[{'name':'n','values':[1,float('nan')]}]), str, 'chart')
    with pytest.raises(ValueError, match='2-16 labels'):
        check_chart(chart(series=[{'name':'n','values':[float('nan'),2,float('nan')]}]), str, 'chart')


def test_box_dictionary_stats_are_normalized_without_inventing_data():
    stats = [{'min':'1','q1':'2','median':'3','q3':'4','max':'5'}] * 3
    result = check_chart(chart(chart_type='box', series=[{'name':'n','stats':stats}]), str, 'chart')
    assert result['series'][0]['stats'] == [[1,2,3,4,5]] * 3


def test_scatter_nan_points_removed():
    points = [[i, str(i)] for i in range(6)] + [[float('nan'),3]]
    result = check_chart(chart(chart_type='scatter',series=[{'name':'n','points':points}]), str, 'chart')
    assert result['series'][0]['points'] == [[float(i),float(i)] for i in range(6)]


@pytest.mark.parametrize('entry', ['module','console'])
def test_actual_cli_process_exits_nonzero_for_failed_bank(entry, tmp_path):
    # Zero budget prevents all HTTP calls even if credentials are present.
    command = [sys.executable, '-m', 'factory.cli'] if entry == 'module' else [str(Path(sys.executable).with_name('factory.exe'))]
    if entry == 'console' and not Path(command[0]).exists():
        pytest.fail('installed factory entry point is required for this regression')
    env = os.environ.copy()
    # Deliberate invalid test credential; max-usd=0 prevents its use.
    import yaml
    config = yaml.safe_load(Path('configs/models.yaml').read_text(encoding='utf-8'))
    env[config['endpoints']['luna']['api_key_env']] = 'offline-unused-test-key'
    output = tmp_path / entry
    log_path = Path('.work') / f'attempt2_exit_{entry}.log'
    with log_path.open('w', encoding='utf-8') as log:
        result = subprocess.run(command + ['content','academic_paper','--n','1','--out',str(output),'--jobs','1','--max-usd','0'],
                                env=env,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode == 1
    record = json.loads((output / 'bank_run.json').read_text(encoding='utf-8'))
    assert record['status'] == 'FAIL' and len(record['failures']) == 1
    assert record['calls'] == []


def test_cli_rejects_persisted_failures_even_if_builder_returns_zero(tmp_path, monkeypatch):
    from argparse import Namespace
    from factory import cli
    async def mistaken_builder(*args, **kwargs):
        (tmp_path / 'bank_run.json').write_text(json.dumps({'status':'FAIL','failures':[{'paper':1}]}),encoding='utf-8')
        return 0
    monkeypatch.setattr(bank, 'build_bank', mistaken_builder)
    args = Namespace(command='content',n=1,out=tmp_path,jobs=1,max_usd=0)
    assert asyncio.run(cli.execute(args)) == 1
