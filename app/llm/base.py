"""Provider-neutral LLM interface.

Internal message format (JSON-serialisable, stored in the DB):
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id","name","arguments","extra"}]}
  {"role": "tool", "tool_call_id", "name", "content": str(JSON), "is_error": bool}
Each provider client converts this to its own SDK format.
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LLMError(Exception):
    pass


class LLMConfigError(LLMError):
    """Missing API key / unknown provider."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    extra: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class LLMClient(ABC):
    provider: str = "base"
    model: str = ""

    @abstractmethod
    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse: ...


def safe_json_loads(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        out = json.loads(value or "{}")
        return out if isinstance(out, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}
