from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


class ToolError(Exception):
    """Expected, LLM-readable tool failure (bad arguments, missing data...)."""


@dataclass
class ToolResult:
    data: Any
    sources: list[dict] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Any, Any], ToolResult]
    needs_db: bool = True
    mutating: bool = False
    requires_approval: bool = False
