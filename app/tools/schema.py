"""Pydantic model -> flat JSON schema that OpenAI, Anthropic and Gemini all accept."""
from pydantic import BaseModel

_DROP = {"title", "default", "$defs"}


def _clean(node, defs):
    if isinstance(node, list):
        return [_clean(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _clean(defs[node["$ref"].split("/")[-1]], defs)
    if "anyOf" in node:
        non_null = [n for n in node["anyOf"] if n.get("type") != "null"]
        if len(non_null) == 1:
            merged = _clean({k: v for k, v in node.items() if k != "anyOf"}, defs)
            merged.update(_clean(non_null[0], defs))
            return merged
    out = {}
    for key, value in node.items():
        if key in _DROP:
            continue
        if key == "properties":
            out[key] = {name: _clean(sub, defs) for name, sub in value.items()}
        else:
            out[key] = _clean(value, defs)
    return out


def to_llm_schema(model: type[BaseModel]) -> dict:
    raw = model.model_json_schema()
    return _clean(raw, raw.get("$defs", {}))
