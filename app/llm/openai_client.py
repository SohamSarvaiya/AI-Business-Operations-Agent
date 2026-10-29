import json

from app.llm.base import LLMClient, LLMResponse, ToolCall, ToolSpec, safe_json_loads


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI  # lazy import

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        kwargs = {"model": self.model, "messages": to_openai_messages(system, messages)}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=safe_json_loads(tc.function.arguments))
            for tc in (msg.tool_calls or [])
            if getattr(tc, "type", "function") == "function"
        ]
        usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens} if resp.usage else {}
        return LLMResponse(text=msg.content or "", tool_calls=calls, usage=usage)
