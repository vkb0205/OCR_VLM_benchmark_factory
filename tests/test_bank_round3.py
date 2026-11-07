"""Offline regressions using original billed disk-cache replies."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from factory.content import bank
from factory.llm import client

REPLAYS = Path(__file__).parent / 'fixtures/bank_replays'


def replay(name):
    return json.loads((REPLAYS / (name + '.json')).read_text(encoding='utf-8'))


@pytest.mark.parametrize('filename', ['5847_4938', '5959_5124'])
def test_recorded_formula_contamination(filename):
    data = client.parse_json(replay(filename)['text'], bank.GroupReply).data
    plan = bank.draw_paper_plan(0, 'materials modelling')
    cleaned = bank.clean_group('formulas', data, plan)
    assert len(cleaned) == 9
    assert all(row['element']['type'] == 'equation' for row in cleaned)
    with pytest.raises(ValueError, match='plan requires'):
        bank.clean_group('formulas', data[:1], plan)


def test_recorded_front_plan_echo_and_body():
    front = client.parse_json(replay('741_7641')['text'], bank.GroupReply).data
    assert {'sections', 'equations', 'tables', 'charts', 'figures', 'code'} <= front.keys()
    assert not (bank.PLAN_KEYS & bank.clean_group('front', front).keys())
    assert set(bank.FRONT) <= bank.clean_group('front', front).keys()
    body = client.parse_json(replay('14305_7926')['text'], bank.GroupReply).data
    # Reproduce the invalid figure reported by final validation, alongside actual prose.
    contaminated = body + [{'type': 'figure', 'id': 'invalid'}]
    assert bank.clean_group('body', contaminated) == body


def test_group_prompt_plan_boundary():
    variables = {'paper_length': 'short', 'element_plan': bank.draw_paper_plan(0, 'materials modelling')}
    prompt = bank.group_prompt('formulas', variables, {})
    assert '"element_plan"' not in prompt
    assert '"chart_types"' not in prompt
    assert '"equation":' in prompt
    assert 'Forbidden element types:' in prompt
    assert 'code' in prompt


def stub_router(monkeypatch, generate):
    class Router:
        def __init__(self, **kwargs):
            pass
        def endpoint(self, agent):
            return client.Endpoint(name='luna', api='openai', model='gpt-6-luna',
                                   api_key_env='unused', params={'reasoning_effort': 'medium'})
    Router.generate = generate
    monkeypatch.setattr(bank, 'Router', Router)


def test_pipeline_repair_uses_bad_reply_and_disables_cache(tmp_path, monkeypatch):
    calls = []
    bad = '{"data": {"bad": "original reply marker"}}'
    async def generate(self, agent, messages, **kwargs):
        calls.append((deepcopy(messages), kwargs))
        if len(calls) == 1:
            return client.LLMResult(text=bad, provider='fake', model='fixture')
        raise RuntimeError('offline stop')
    stub_router(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(1, tmp_path, jobs=1)) == 1
    assert len(calls) == 2
    assert calls[0][0] != calls[1][0]
    assert bad in calls[1][0][-1]['content']
    assert 'front: expected an object' in calls[1][0][-1]['content']
    assert calls[0][1]['use_cache'] is True
    assert calls[1][1]['use_cache'] is False


def test_resume_all_accepted_attempt1_groups_and_continue_failures(tmp_path, monkeypatch):
    # Copy historical checkpoints to temporary test output; never mutate the bank.
    source = REPLAYS
    for index in (1, 3):
        groups = json.loads((source / f'.paper_{index:02}.groups.json').read_text(encoding='utf-8'))
        (tmp_path / f'.paper_{index:02}.groups.json').write_text(json.dumps(groups), encoding='utf-8')
    calls = []
    async def generate(self, agent, messages, **kwargs):
        prompt = messages[-1]['content']
        calls.append(prompt)
        raise RuntimeError('offline unavailable')
    stub_router(monkeypatch, generate)
    # Full paper validation is unrelated to checkpoint reuse here.
    monkeypatch.setattr(bank, 'validate_paper', lambda paper: None)
    assert asyncio.run(bank.build_bank(3, tmp_path, jobs=1)) == 1
    assert len(calls) == 2  # paper 1 missing formulas; paper 2 missing front; paper 3 complete
    assert (tmp_path / 'paper_03.json').exists()
    assert (tmp_path / 'paper_03.profile.json').exists()
    record = json.loads((tmp_path / 'bank_run.json').read_text(encoding='utf-8'))
    assert [f['paper'] for f in record['failures']] == [1, 2]
    assert record['papers'][0]['content_id'] == 'paper_03'


def test_cost_guard_stops_before_first_call(tmp_path, monkeypatch):
    async def generate(*args, **kwargs):
        pytest.fail('budget must prevent model invocation')
    stub_router(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(3, tmp_path, jobs=1, max_usd=0)) == 1
    record = json.loads((tmp_path / 'bank_run.json').read_text(encoding='utf-8'))
    assert record['calls'] == []
    assert len(record['failures']) == 3


def test_statusless_sdk_apierror_retries_and_repair_bypasses_disk_cache(tmp_path, monkeypatch):
    import httpx
    import openai
    router = client.Router(cache_dir=tmp_path)
    endpoint = client.Endpoint(name='test', api='openai', model='fixture', api_key_env='unused')
    count = 0
    async def transport(endpoint, messages):
        nonlocal count
        count += 1
        if count < 3:
            raise openai.APIError('recorded status-less streaming failure',
                                  httpx.Request('POST', 'https://offline.invalid'), body=None)
        return str(count), 1, 1
    async def no_wait(delay):
        pass
    monkeypatch.setitem(client.CALLS, 'openai', transport)
    monkeypatch.setattr(client.asyncio, 'sleep', no_wait)
    first = asyncio.run(router.complete(endpoint, []))
    assert count == 3
    assert asyncio.run(router.complete(endpoint, [])).cached
    repaired = asyncio.run(router.complete(endpoint, [], use_cache=False))
    assert count == 4 and not repaired.cached and repaired.text != first.text
    assert asyncio.run(router.complete(endpoint, [])).text == first.text


def test_cost_guard_stops_later_calls_after_billed_reply(tmp_path, monkeypatch):
    calls = []
    async def generate(self, agent, messages, **kwargs):
        calls.append(messages)
        return client.LLMResult(text=replay('741_5139')['text'], provider='fake',
                                model='fixture', cost_usd=0.11)
    stub_router(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(3, tmp_path, jobs=1, max_usd=0.10)) == 1
    assert len(calls) == 1
    record = json.loads((tmp_path / 'bank_run.json').read_text(encoding='utf-8'))
    assert record['cost_usd'] == 0.11
    assert (tmp_path / '.paper_01.groups.json').exists()


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_transport_does_not_retry_client_errors(status):
    error = type('APIError', (Exception,), {'status_code': status})()
    assert not client._retryable_transport_error(error)


def test_recorded_replies_through_generation_pipeline(tmp_path, monkeypatch):
    calls = []
    async def generate(self, agent, messages, **kwargs):
        calls.append((messages, kwargs))
        if len(calls) <= 2:
            name = ['741_5139', '5847_4938'][len(calls)-1]
            return client.LLMResult.model_validate(replay(name))
        raise RuntimeError('offline stop after accepted formula checkpoint')
    stub_router(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(1, tmp_path, jobs=1)) == 1
    checkpoint = json.loads((tmp_path / '.paper_01.groups.json').read_text(encoding='utf-8'))
    assert len(checkpoint['formulas']) == 9
    assert all(x['element']['type'] == 'equation' for x in checkpoint['formulas'])
    assert len(calls) == 3
    assert all(kwargs['use_cache'] for _, kwargs in calls)


def test_actual_checkpoint_validation_routes_invalid_float_ids_to_owner(tmp_path, monkeypatch):
    checkpoint = (REPLAYS / '.paper_03.groups.json').read_text(encoding='utf-8')
    (tmp_path / '.paper_03.groups.json').write_text(checkpoint, encoding='utf-8')
    calls = []
    async def generate(self, agent, messages, **kwargs):
        calls.append((messages[-1]['content'], kwargs))
        raise RuntimeError('offline stop on repair')
    stub_router(monkeypatch, generate)
    assert asyncio.run(bank.build_bank(3, tmp_path, jobs=1)) == 1
    # Papers 1/2 stop at front. Paper 3 reuses all groups, then validates for real.
    prompt, kwargs = calls[-1]
    assert 'id must look like fig:name' in prompt
    assert '"id": "fig:F1"' in prompt
    assert 'Repair only this group:' in prompt
    assert kwargs['use_cache'] is False
    assert 'typed_chart_or_figure' in prompt
