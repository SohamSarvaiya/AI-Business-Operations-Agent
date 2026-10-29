import base64
import json
import uuid

from app.llm.base import LLMClient, LLMResponse, ToolCall, ToolSpec


def to_gemini_contents(messages: list[dict]):
    from google.genai import types

    contents: list = []
    for m in messages:
        if m["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif m["role"] == "assistant":
            parts = []
            if m.get("content"):
                parts.append(types.Part(text=m["content"]))
            for tc in m.get("tool_calls") or []:
                kwargs = {"function_call": types.FunctionCall(name=tc["name"], args=tc["arguments"])}
                sig = (tc.get("extra") or {}).get("thought_signature")
                if sig:  # Gemini 3 requires thought signatures to be passed back
                    kwargs["thought_signature"] = base64.b64decode(sig)
                parts.append(types.Part(**kwargs))
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="(empty)")]))
        elif m["role"] == "tool":
            try:
                payload = json.loads(m["content"])
            except json.JSONDecodeError:
                payload = m["content"]
            part = types.Part.from_function_response(name=m["name"], response={"result": payload})
            last = contents[-1] if contents else None
            if last is not None and last.role == "user" and last.parts and last.parts[0].function_response is not None:
                last.parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return contents


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, api_key: str, model: str):
        from google import genai  # lazy import

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        from google.genai import types

        decls = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                # Gemini rejects OBJECT schemas with empty properties
                parameters=t.parameters if t.parameters.get("properties") else None,
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self.client.models.generate_content(model=self.model, contents=to_gemini_contents(messages), config=config)
        text, calls = [], []
        candidate = resp.candidates[0] if resp.candidates else None
        for part in (candidate.content.parts or []) if candidate and candidate.content else []:
            if part.function_call:
                extra = {}
                if getattr(part, "thought_signature", None):
                    extra["thought_signature"] = base64.b64encode(part.thought_signature).decode()
                calls.append(ToolCall(id=f"gemini_{uuid.uuid4().hex[:12]}", name=part.function_call.name,
                                      arguments=dict(part.function_call.args or {}), extra=extra))
            elif part.text and not getattr(part, "thought", False):
                text.append(part.text)
        um = resp.usage_metadata
        usage = {"input_tokens": um.prompt_token_count, "output_tokens": um.candidates_token_count} if um else {}
        return LLMResponse(text="\n".join(text), tool_calls=calls, usage=usage)
