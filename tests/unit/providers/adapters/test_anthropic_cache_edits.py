"""The Anthropic provider sends the caller's cache edits, and only to [1m] models."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from openprogram.models.providers.adapters.anthropic import anthropic
from openprogram.models.providers.types import Context, Model, SimpleStreamOptions

EDITS = {"context_management": {"edits": [{
    "type": "clear_tool_uses_20250919",
    "keep": {"type": "tool_uses", "value": 5},
}]}}


class _Stream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def get_final_message(self):
        return NS(usage=NS(input_tokens=1, output_tokens=1), stop_reason="end_turn")


def _request_params(monkeypatch, model_id, cache_edits):
    params = {}

    def stream(**kwargs):
        params.update(kwargs)
        return _Stream()

    monkeypatch.setattr("openprogram.models.auth.usage.acquire_pooled", lambda *args: None)
    monkeypatch.setattr(
        anthropic, "_build_client",
        lambda *args, **kwargs: (NS(messages=NS(stream=stream)), False),
    )
    model = Model(id=model_id, name="test", provider="anthropic", api="anthropic-messages",
                  base_url="https://api.anthropic.com")
    options = SimpleStreamOptions(api_key="test", cache_edits=cache_edits)

    async def run():
        return [event async for event in anthropic.stream_simple(model, Context(messages=[]), options)]

    asyncio.run(run())
    return params


def test_1m_model_merges_cache_edits_into_extra_body(monkeypatch):
    calls = []

    def edits():
        calls.append(1)
        return EDITS

    params = _request_params(monkeypatch, "claude-opus-4-6[1m]", edits)
    assert params["extra_body"] == EDITS
    assert calls == [1]


def test_no_edit_this_turn_leaves_body_alone(monkeypatch):
    params = _request_params(monkeypatch, "claude-opus-4-6[1m]", lambda: None)
    assert "extra_body" not in params


def test_plain_model_never_calls_cache_edits(monkeypatch):
    def edits():
        raise AssertionError("cache edits must not fire for a model without the beta header")

    params = _request_params(monkeypatch, "claude-opus-4-6", edits)
    assert "extra_body" not in params


def test_no_option_and_no_registered_default_sends_none(monkeypatch):
    monkeypatch.setattr("openprogram.models.cache_edits._default", None)
    params = _request_params(monkeypatch, "claude-opus-4-6[1m]", None)
    assert "extra_body" not in params


@pytest.fixture
def fifty_tool_calls():
    """The runtime registered its producer and this run made 50 tool calls."""
    import openprogram.runtime  # noqa: F401 - registers the default producer
    from openprogram.runtime.context.compaction import cache_aware_microcompact

    cache_aware_microcompact.reset()
    cache_aware_microcompact.increment_tool_calls(cache_aware_microcompact.INITIAL_TRIGGER)
    yield cache_aware_microcompact
    cache_aware_microcompact.reset()


def test_a_request_without_the_option_uses_the_runtime_producer(monkeypatch, fifty_tool_calls):
    params = _request_params(monkeypatch, "claude-opus-4-6[1m]", None)
    assert params["extra_body"]["context_management"]["edits"][0]["type"] == "clear_tool_uses_20250919"


def test_a_summary_request_on_a_1m_model_carries_the_context_edits(monkeypatch, fifty_tool_calls):
    """Compaction summaries build their own options without cache_edits; the
    body still carries context_management, as every Anthropic request did."""
    from openprogram.runtime.context.compaction.bounded_summary import summarize_text

    params = {}

    def stream(**kwargs):
        params.update(kwargs)
        return _Stream()

    monkeypatch.setattr("openprogram.models.auth.usage.acquire_pooled", lambda *args: None)
    monkeypatch.setattr(
        anthropic, "_build_client",
        lambda *args, **kwargs: (NS(messages=NS(stream=stream)), False),
    )
    model = Model(id="claude-opus-4-6[1m]", name="test", provider="anthropic",
                  api="anthropic-messages", base_url="https://api.anthropic.com",
                  context_window=1_000_000, max_tokens=32_000)

    with pytest.raises(ValueError):  # the stub stream returns no summary text
        asyncio.run(summarize_text(
            "User: hello", model, SimpleStreamOptions(api_key="test"),
            instruction="Summarize.", max_tokens=1000,
        ))
    assert params["extra_body"] == {"context_management": {"edits": [{
        "type": "clear_tool_uses_20250919",
        "keep": {"type": "tool_uses", "value": fifty_tool_calls.KEEP_RECENT},
    }]}}
