import json

import pytest

from app.config import Settings
from app.llm.anthropic_client import to_anthropic_messages
from app.llm.base import LLMConfigError
from app.llm.factory import get_llm_client
from app.llm.openai_client import to_openai_messages

MSGS = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "name": "a", "arguments": {"x": 1}, "extra": {}},
        {"id": "c2", "name": "b", "arguments": {}, "extra": {}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "a", "content": '{"ok": true}', "is_error": False},
    {"role": "tool", "tool_call_id": "c2", "name": "b", "content": '{"ok": false}', "is_error": True},
]


def test_openai_conversion():
    out = to_openai_messages("sys", MSGS)
    assert out[0] == {"role": "system", "content": "sys"}
    assert json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"x": 1}
    assert [m["role"] for m in out[3:]] == ["tool", "tool"]


def test_anthropic_conversion_merges_tool_results():
    out = to_anthropic_messages(MSGS)
    assert out[1]["content"][0]["type"] == "tool_use"
    assert len(out) == 3 and len(out[2]["content"]) == 2          # both results in ONE user message
    assert out[2]["content"][1]["is_error"] is True


def test_gemini_conversion():
    pytest.importorskip("google.genai")
    from app.llm.gemini_client import to_gemini_contents

    out = to_gemini_contents(MSGS)
    assert out[1].role == "model" and out[1].parts[0].function_call.name == "a"
    assert out[2].role == "user" and len(out[2].parts) == 2 and out[2].parts[0].function_response.name == "a"


def test_factory_requires_keys_and_supports_all_providers():
    s = Settings(_env_file=None)
    for name in ("openai", "anthropic", "gemini"):
        with pytest.raises(LLMConfigError):
            get_llm_client(name, s)
    with pytest.raises(LLMConfigError):
        get_llm_client("nope", s)
    assert get_llm_client("mock", s).provider == "mock"
    assert get_llm_client("openai", Settings(openai_api_key="sk-test", _env_file=None)).provider == "openai"
    assert get_llm_client("anthropic", Settings(anthropic_api_key="sk-ant-test", _env_file=None)).provider == "anthropic"
    assert get_llm_client("gemini", Settings(gemini_api_key="g-test", _env_file=None)).provider == "gemini"


def test_factory_ui_key_overrides_env():
    s = Settings(_env_file=None)                       # no keys in env
    c = get_llm_client("openai", s, api_key="sk-ui", model="my-model")
    assert c.provider == "openai" and c.model == "my-model"
    assert get_llm_client("anthropic", s, api_key="k").model == s.anthropic_model
