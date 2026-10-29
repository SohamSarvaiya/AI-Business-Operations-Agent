from app.llm.base import LLMClient, LLMResponse, ToolCall, ToolSpec


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(empty)"}]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"],
                     "is_error": bool(m.get("is_error"))}
            last = out[-1] if out else None
            if last and last["role"] == "user" and isinstance(last["content"], list) \
                    and last["content"] and last["content"][0].get("type") == "tool_result":
                last["content"].append(block)  # all results of one assistant turn go in ONE user message
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic  # lazy import

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        kwargs = {"model": self.model, "max_tokens": 4096, "system": system,
                  "messages": to_anthropic_messages(messages)}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        resp = self.client.messages.create(**kwargs)
        text, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return LLMResponse(text="\n".join(text), tool_calls=calls, usage=usage)
