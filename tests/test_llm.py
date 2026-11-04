import asyncio

import pytest
from pydantic import BaseModel

from factory.llm import client


class Reply(BaseModel):
    values: dict


@pytest.mark.parametrize("text", [
    '{"values":{"x":1}}} trailing text',
    '{"values":{"x":[1,2,],},}',
    '{"values":{"x":[1,2]',
    '```json\n{"values":{"x":1}}\n```',
])
def test_parse_json_repairs_common_model_output(text):
    assert client.parse_json(text, Reply).values["x"]


def test_router_retries_only_transport_failures(tmp_path, monkeypatch):
    config = tmp_path / "models.yaml"
    config.write_text(
        "endpoints:\n  test:\n    api: openai\n    model: test\n    api_key_env: TEST_API_KEY\n"
        "agents: {}\n"
    )
    monkeypatch.setenv("TEST_API_KEY", "test")
    router = client.Router(config=config, cache_dir=None)
    calls = 0

    async def flaky(endpoint, messages):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("temporary disconnect")
        return '{"ok":true}', 12, 4

    async def no_wait(_delay):
        return None

    monkeypatch.setitem(client.CALLS, "openai", flaky)
    monkeypatch.setattr(client.asyncio, "sleep", no_wait)
    result = asyncio.run(router.complete(router.endpoint("test"), []))
    assert result.tokens_in == 12
    assert calls == 3


def test_router_does_not_nest_schema_retries(tmp_path, monkeypatch):
    config = tmp_path / "models.yaml"
    config.write_text(
        "endpoints:\n  test:\n    api: openai\n    model: test\n    api_key_env: TEST_API_KEY\n"
        "agents: {}\n"
    )
    monkeypatch.setenv("TEST_API_KEY", "test")
    router = client.Router(config=config, cache_dir=None)
    calls = 0

    async def once(endpoint, messages):
        nonlocal calls
        calls += 1
        return client.LLMResult(text="not json", provider="test", model="test")

    monkeypatch.setattr(router, "complete", once)
    with pytest.raises(ValueError):
        asyncio.run(router.generate("test", [], schema=Reply))
    assert calls == 1
