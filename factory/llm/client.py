"""One LLM interface over Anthropic and OpenAI-compatible endpoints, with a disk cache.

`configs/models.yaml` lists endpoints in priority order. Each names its API
(`anthropic` or `openai`), model, credential variable and optional base URL;
the model and base URL can also come from environment variables.
An agent uses its configured endpoint, or else the first endpoint whose
credentials are set, so entering a key is enough to route to that provider.
"""

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import tempfile
import asyncio
import copy
from typing import Protocol

from pydantic import BaseModel, ValidationError
import yaml

ROOT = Path(__file__).resolve().parents[2]


class LLMResult(BaseModel):
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0
    cached: bool = False


class LLMClient(Protocol):
    async def generate(self, agent: str, messages, *, schema: type[BaseModel] | None = None,
                       images: list[bytes] = (), temperature: float | None = None) -> LLMResult: ...


def parse_json(text: str, schema: type[BaseModel]) -> BaseModel:
    """Parse JSON after local repairs for common formatting mistakes."""
    body = re.sub(r'^\s*<thinking>.*?</thinking>\s*', '', text, flags=re.S).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.S | re.I)
    if fenced:
        body = fenced[1].strip()

    candidates = [body]
    balanced = _first_balanced_object(body)
    if balanced and balanced != body:
        candidates.append(balanced)
    candidates.extend(_repair_json_candidates(body))
    if balanced and balanced != body:
        candidates.extend(_repair_json_candidates(balanced))

    seen = set()
    last_error = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        return schema.model_validate(value)
    raise ValueError(f"Invalid JSON: {last_error}") from last_error


def _first_balanced_object(text: str) -> str | None:
    """Return the first complete top-level JSON object, ignoring braces in strings."""
    start = text.find("{")
    if start < 0:
        return None
    stack = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack[-1] != pairs[char]:
                return None
            stack.pop()
            if not stack:
                return text[start:index + 1]
    return None


def _repair_json_candidates(text: str) -> list[str]:
    start = text.find("{")
    if start < 0:
        return []
    body = text[start:].strip()
    candidates = []
    comma_fixed = _remove_trailing_commas(body)
    candidates.append(comma_fixed)

    stack = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for char in comma_fixed:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
            else:
                break
    if stack and not in_string:
        candidates.append(comma_fixed + "".join("}" if char == "{" else "]" for char in reversed(stack)))
    return candidates


def _remove_trailing_commas(text: str) -> str:
    output = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


class FakeProvider:
    """Return supplied fixtures for the agent; no keys, HTTP or model calls.

    A list fixture is consumed one reply per call, for multi-turn agents.
    """

    def __init__(self, fixtures: dict | None = None):
        self.fixtures = {k: list(v) if isinstance(v, list) else v for k, v in (fixtures or {}).items()}
        self.calls = []

    async def generate(self, agent, messages, *, schema=None, images=(), temperature=None):
        self.calls.append({"agent": agent, "messages": copy.deepcopy(messages), "images": list(images)})
        value = self.fixtures[agent]
        if isinstance(value, list):
            value = value.pop(0)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if schema is not None:
            text = parse_json(text, schema).model_dump_json()
        return LLMResult(text=text, provider="fake", model="fixture")


class Endpoint(BaseModel):
    name: str
    api: str  # anthropic | openai
    model: str
    api_key_env: str
    base_url: str | None = None
    base_url_env: str | None = None
    model_env: str | None = None  # overrides `model` when set
    json_mode: bool = False
    max_tokens: int = 64000
    price_in: float = 0  # USD per million tokens, for trace cost
    price_out: float = 0
    params: dict = {}  # passed through to the provider request

    def key(self):
        return os.environ.get(self.api_key_env)

    def model_name(self):
        return (os.environ.get(self.model_env) if self.model_env else None) or self.model

    def url(self):
        url = (os.environ.get(self.base_url_env) if self.base_url_env else None) or self.base_url
        if url:
            # The SDK appends the endpoint path itself; accept a URL copied with it.
            url = re.sub(r"/(?:chat/completions|responses|messages)/?$", "", url.strip())
        return url


def load_env(path: Path = ROOT / ".env"):
    """Read KEY=VALUE lines without overriding variables already exported."""
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def call_anthropic(endpoint: Endpoint, messages):
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=endpoint.key(), base_url=endpoint.url())
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    params = dict(endpoint.params)
    request = dict(model=endpoint.model_name(), max_tokens=endpoint.max_tokens,
                   messages=[m for m in messages if m["role"] != "system"], **params)
    if system:
        request["system"] = system
    # Streaming avoids HTTP timeouts on long JSON and page outputs.
    stream = client.beta.messages.stream if "betas" in params else client.messages.stream
    async with stream(**request) as response:
        message = await response.get_final_message()
    if message.stop_reason == "refusal":
        raise RuntimeError(f"{endpoint.model_name()} refused the request")
    if message.stop_reason == "max_tokens":
        # Keep the partial text: it fails JSON parsing and the caller asks again with the same task.
        from factory.log import log
        log(f"{endpoint.model_name()} stopped at max_tokens={endpoint.max_tokens}; reply is incomplete")
    text = "".join(block.text for block in message.content if block.type == "text")
    return text, message.usage.input_tokens, message.usage.output_tokens


async def call_openai(endpoint: Endpoint, messages):
    import openai
    client = openai.AsyncOpenAI(api_key=endpoint.key(), base_url=endpoint.url(), timeout=1800)
    # Streaming avoids gateway timeouts on long JSON outputs.
    params = dict(endpoint.params)
    if endpoint.json_mode:
        params.setdefault("response_format", {"type": "json_object"})
    stream = await client.chat.completions.create(model=endpoint.model_name(), messages=messages,
                                                  max_completion_tokens=endpoint.max_tokens, stream=True,
                                                  stream_options={"include_usage": True}, **params)
    parts, finish, usage = [], None, None
    async for chunk in stream:
        usage = chunk.usage or usage
        for choice in chunk.choices:
            parts.append(choice.delta.content or "")
            finish = choice.finish_reason or finish
    if finish == "length":
        # Keep the partial text: it fails JSON parsing and the caller asks again with the same task.
        from factory.log import log
        log(f"{endpoint.model_name()} stopped at max_tokens={endpoint.max_tokens}; reply is incomplete")
    return "".join(parts), getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0)


CALLS = {"anthropic": call_anthropic, "openai": call_openai}


class Router:
    """Route each agent to an endpoint with credentials; cache replies on disk."""

    def __init__(self, config: Path = ROOT / "configs/models.yaml", cache_dir: Path | None = ROOT / ".cache/llm",
                 force: str | None = None):
        load_env()
        data = yaml.safe_load(config.read_text()) or {}
        self.endpoints = [Endpoint(name=name, **value) for name, value in (data.get("endpoints") or {}).items()]
        unknown = {e.api for e in self.endpoints} - set(CALLS)
        if unknown:
            raise ValueError(f"Unknown LLM api in {config}: {unknown}")
        self.agents = data.get("agents") or {}
        # USD per million tokens by model name; wins over an endpoint's price_in/price_out,
        # because model_env can swap the model behind an endpoint.
        self.prices = {str(model): tuple(price) for model, price in (data.get("prices") or {}).items()}
        self.unpriced: set[str] = set()
        self.force, self.cache_dir = force, cache_dir

    def endpoint(self, agent: str) -> Endpoint:
        by_name = {e.name: e for e in self.endpoints}
        wanted = self.force or self.agents.get(agent)
        if wanted:
            if wanted not in by_name:
                raise ValueError(f"No endpoint named {wanted} in configs/models.yaml")
            if not by_name[wanted].key():
                raise RuntimeError(f"Endpoint {wanted} needs {by_name[wanted].api_key_env} to be set")
            return by_name[wanted]
        for endpoint in self.endpoints:
            if endpoint.key():
                return endpoint
        names = ", ".join(sorted({e.api_key_env for e in self.endpoints}))
        raise RuntimeError(f"No LLM credentials found; set one of {names} (shell or .env)")

    async def generate(self, agent, messages, *, schema=None, images=(), temperature=None):
        endpoint = self.endpoint(agent)
        messages = _attach_images(list(messages), endpoint.api, images)
        result = await self.complete(endpoint, messages)
        if schema is None:
            return result
        try:
            parsed = parse_json(result.text, schema)
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"{endpoint.model_name()} returned invalid JSON for {schema.__name__}: {exc}") from exc
        return result.model_copy(update={"text": parsed.model_dump_json()})

    async def tool_turn(self, agent: str, messages, tools) -> "ToolTurn":
        """One turn of a tool-using session. Not cached: tool results depend on the live render."""
        endpoint = self.endpoint(agent)
        for attempt in range(3):
            try:
                text, calls, message, tokens_in, tokens_out = await TOOL_CALLS[endpoint.api](endpoint, messages, tools)
                break
            except Exception as exc:
                if attempt == 2 or not _retryable_transport_error(exc):
                    raise
                from factory.log import log, short
                log(f"transport error, retry {attempt + 1}/2: {short(exc, 120)}")
                await asyncio.sleep(0.5 * (2 ** attempt))
        model = endpoint.model_name()
        price_in, price_out = self.prices.get(model, (endpoint.price_in, endpoint.price_out))
        result = LLMResult(text=text, provider=endpoint.api, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=(tokens_in * price_in + tokens_out * price_out) / 1e6)
        return ToolTurn(text=text, calls=calls, message=message, result=result)

    async def complete(self, endpoint: Endpoint, messages) -> LLMResult:
        request = {"api": endpoint.api, "model": endpoint.model_name(), "base_url": endpoint.url(),
                   "params": endpoint.params, "json_mode": endpoint.json_mode,
                   "max_tokens": endpoint.max_tokens, "messages": messages}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / f"{digest}.json" if self.cache_dir else None
        if path and path.is_file():
            return LLMResult.model_validate_json(path.read_text()).model_copy(update={"cached": True, "cost_usd": 0})
        for attempt in range(3):
            try:
                text, tokens_in, tokens_out = await CALLS[endpoint.api](endpoint, messages)
                break
            except Exception as exc:
                if attempt == 2 or not _retryable_transport_error(exc):
                    raise
                from factory.log import log, short
                log(f"transport error, retry {attempt + 1}/2: {short(exc, 120)}")
                await asyncio.sleep(0.5 * (2 ** attempt))
        model = endpoint.model_name()
        price_in, price_out = self.prices.get(model, (endpoint.price_in, endpoint.price_out))
        if not (price_in or price_out) and model not in self.unpriced:
            self.unpriced.add(model)
            from factory.log import log
            log(f"no price for model {model}; add it under `prices` in configs/models.yaml (cost_usd will be 0)")
        result = LLMResult(text=text, provider=endpoint.api, model=model, tokens_in=tokens_in,
                           tokens_out=tokens_out,
                           cost_usd=(tokens_in * price_in + tokens_out * price_out) / 1e6)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Concurrent runs must never observe a partially written cache entry.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(result.model_dump_json())
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return result


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class ToolTurn(BaseModel):
    """One model turn of a tool-using session. `message` is the assistant message in OpenAI chat format."""
    text: str
    calls: list[ToolCall]
    message: dict
    result: LLMResult


def _tool_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_invalid_json": str(raw)[:2000]}
    return value if isinstance(value, dict) else {"_invalid_json": str(raw)[:2000]}


async def tool_openai(endpoint: Endpoint, messages, tools):
    import openai
    client = openai.AsyncOpenAI(api_key=endpoint.key(), base_url=endpoint.url(), timeout=1800)
    params = {k: v for k, v in endpoint.params.items() if k != "response_format"}
    response = await client.chat.completions.create(
        model=endpoint.model_name(), messages=messages, max_completion_tokens=endpoint.max_tokens,
        tools=[{"type": "function", "function": tool} for tool in tools], **params)
    choice = response.choices[0].message
    calls = [ToolCall(id=c.id, name=c.function.name, arguments=_tool_arguments(c.function.arguments))
             for c in (choice.tool_calls or [])]
    message = {"role": "assistant", "content": choice.content or ""}
    if choice.tool_calls:
        message["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                 for c in choice.tool_calls]
    usage = response.usage
    return choice.content or "", calls, message, getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0)


def _to_anthropic(messages):
    """OpenAI chat messages (with tool calls and tool results) to Anthropic system + messages."""
    system, out = [], []
    def add(role, blocks):
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    for m in messages:
        content = m.get("content")
        if m["role"] == "system":
            system.append(content)
        elif m["role"] == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content or ""}])
        elif m["role"] == "assistant":
            blocks = [{"type": "text", "text": content}] if content else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                        "input": _tool_arguments(c["function"]["arguments"])} for c in m.get("tool_calls", [])]
            add("assistant", blocks)
        else:
            blocks = []
            for part in content if isinstance(content, list) else [{"type": "text", "text": str(content)}]:
                if part.get("type") == "image_url":
                    data = part["image_url"]["url"].split(",", 1)[1]
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
                else:
                    blocks.append(part)
            add("user", blocks)
    return "\n\n".join(system), out


async def tool_anthropic(endpoint: Endpoint, messages, tools):
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=endpoint.key(), base_url=endpoint.url())
    system, converted = _to_anthropic(messages)
    params = dict(endpoint.params)
    request = dict(model=endpoint.model_name(), max_tokens=endpoint.max_tokens, messages=converted,
                   tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                          for t in tools], **params)
    if system:
        request["system"] = system
    stream = client.beta.messages.stream if "betas" in params else client.messages.stream
    async with stream(**request) as response:
        message = await response.get_final_message()
    text = "".join(b.text for b in message.content if b.type == "text")
    calls = [ToolCall(id=b.id, name=b.name, arguments=b.input if isinstance(b.input, dict) else {})
             for b in message.content if b.type == "tool_use"]
    out = {"role": "assistant", "content": text}
    if calls:
        out["tool_calls"] = [{"id": c.id, "type": "function",
                              "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                             for c in calls]
    return text, calls, out, message.usage.input_tokens, message.usage.output_tokens


TOOL_CALLS = {"anthropic": tool_anthropic, "openai": tool_openai}


def _retryable_transport_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429 or (isinstance(status, int) and 500 <= status <= 599):
        return True
    name = type(exc).__name__.lower()
    return isinstance(exc, (ConnectionError, OSError, TimeoutError)) or any(
        marker in name for marker in ("connection", "connecterror", "timeout", "networkerror")
    )


def _attach_images(messages, api: str, images):
    if not images:
        return messages
    if not messages or messages[-1].get("role") != "user":
        messages.append({"role": "user", "content": "Review the attached contact sheet."})
    message = messages[-1]
    content = message.get("content", "")
    if not isinstance(content, list):
        content = [{"type": "text", "text": str(content)}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        if api == "anthropic":
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": encoded},
            })
        else:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            })
    message["content"] = content
    return messages
