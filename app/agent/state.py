from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    run_id: str
    request: str
    messages: list[dict]          # provider-neutral conversation
    pending_calls: list[dict]     # tool calls waiting to be executed / approved
    approval: str | None          # None | "approved" | "rejected"
    tool_logs: list[dict]         # execution log (also persisted in tool_logs table)
    report: dict[str, Any] | None
    status: str                   # running | awaiting_approval | completed | failed
    error: str | None
    iterations: int
    nudges: int
