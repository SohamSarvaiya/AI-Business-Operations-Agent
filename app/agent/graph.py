"""LangGraph workflow.

START -> (agent | tools) ; agent -> tools | nudge | END ; nudge -> agent ; tools -> agent | END
`tools` pauses with status=awaiting_approval when a tool requires human approval; the run is resumed
(START -> tools) once a decision is stored in state["approval"].
"""
import json
import time
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState
from app.llm.base import LLMClient
from app.schemas import BusinessReport, DataSource, ReportSubmission
from app.tools import SUBMIT_REPORT, ToolRegistry
from app.tools.base import ToolError

NUDGE = ("Reply with tool calls only. When your analysis is complete, call submit_report with the final structured report.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_message(call: dict, payload: dict, is_error: bool, max_chars: int) -> dict:
    content = json.dumps(payload, default=str)
    if len(content) > max_chars:
        content = json.dumps({"ok": payload.get("ok"), "truncated": True, "data_preview": content[:max_chars]})
    return {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": content, "is_error": is_error}


def build_report(submission: ReportSubmission, logs: list[dict]) -> dict:
    """Attach data sources from what the tools REALLY did (not what the LLM claims)."""
    seen, sources = set(), []
    for log in logs:
        if log["status"] != "ok" or log["tool"] == SUBMIT_REPORT:
            continue
        for src in log.get("sources", []):
            key = (log["tool"], src["source_type"], tuple(src["tables"]), src["detail"])
            if key not in seen:
                seen.add(key)
                sources.append(DataSource(tool=log["tool"], **src))
    return BusinessReport(**submission.model_dump(), data_sources=sources).model_dump()


def build_graph(llm: LLMClient, registry: ToolRegistry, settings):
    specs = registry.specs()
    system = build_system_prompt(settings, write_tools=any(t.mutating for t in registry.all()))

    def entry_router(state: AgentState) -> str:
        return "tools" if state.get("pending_calls") and state.get("approval") else "agent"

    def chat_with_retry(messages):
        last = None
        for attempt in range(max(1, settings.llm_max_retries)):
            try:
                return llm.chat(system, messages, specs)
            except Exception as exc:  # network / rate limit / provider errors
                last = exc
                if attempt + 1 < settings.llm_max_retries:
                    time.sleep(settings.llm_retry_backoff_seconds * (2 ** attempt))
        raise last

    def agent_node(state: AgentState):
        iterations = state.get("iterations", 0) + 1
        if iterations > settings.max_iterations:
            return {"status": "failed", "error": f"Stopped: exceeded max_iterations={settings.max_iterations}."}
        try:
            resp = chat_with_retry(state["messages"])
        except Exception as exc:
            return {"status": "failed", "error": f"LLM call failed: {type(exc).__name__}: {exc}"}
        calls = [{"id": c.id, "name": c.name, "arguments": c.arguments, "extra": c.extra} for c in resp.tool_calls]
        message = {"role": "assistant", "content": resp.text, "tool_calls": calls}
        return {"messages": state["messages"] + [message], "pending_calls": calls, "iterations": iterations, "status": "running"}

    def after_agent(state: AgentState) -> str:
        if state.get("status") == "failed":
            return END
        return "tools" if state.get("pending_calls") else "nudge"

    def nudge_node(state: AgentState):
        nudges = state.get("nudges", 0) + 1
        if nudges > settings.max_nudges:
            return {"status": "failed", "error": "Model did not call any tool / submit_report."}
        return {"nudges": nudges, "messages": state["messages"] + [{"role": "user", "content": NUDGE}]}

    def after_nudge(state: AgentState) -> str:
        return END if state.get("status") == "failed" else "agent"

    def tools_node(state: AgentState):
        messages = list(state.get("messages", []))
        logs = list(state.get("tool_logs", []))
        pending = list(state.get("pending_calls", []))
        decision = state.get("approval")
        report = None

        for idx, call in enumerate(pending):
            tool = registry.get(call["name"])
            needs_approval = bool(tool and tool.requires_approval)
            if needs_approval and decision is None:  # human-in-the-loop pause
                return {"messages": messages, "tool_logs": logs, "pending_calls": pending[idx:], "status": "awaiting_approval"}

            started = time.perf_counter()
            log = {"tool": call["name"], "arguments": call["arguments"], "status": "ok", "error": None, "sources": [],
                   "result_preview": "", "approval": decision if needs_approval else None, "timestamp": _now()}
            is_error = False
            try:
                if needs_approval and decision == "rejected":
                    log["status"] = "rejected"
                    is_error = True
                    payload = {"ok": False, "error": "Rejected by human approver. Do not retry; continue without this action."}
                else:
                    result = registry.execute(call["name"], call["arguments"])
                    log["sources"] = result.sources
                    log["result_preview"] = json.dumps(result.data, default=str)[:500]
                    payload = {"ok": True, "data": result.data}
                    if call["name"] == SUBMIT_REPORT:
                        report = build_report(ReportSubmission.model_validate(call["arguments"]), logs)
            except ToolError as exc:
                log["status"], log["error"], is_error = "error", str(exc), True
                payload = {"ok": False, "error": str(exc)}
            except Exception as exc:  # unexpected - still never crash the run
                log["status"], log["error"], is_error = "error", f"{type(exc).__name__}: {exc}", True
                payload = {"ok": False, "error": f"Internal tool error: {type(exc).__name__}: {exc}"}
            log["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            logs.append(log)
            messages.append(_tool_message(call, payload, is_error, settings.tool_result_max_chars))

        update = {"messages": messages, "tool_logs": logs, "pending_calls": [], "approval": None, "status": "running"}
        if report is not None:
            update.update(report=report, status="completed")
        return update

    def after_tools(state: AgentState) -> str:
        return END if state.get("status") in ("awaiting_approval", "completed", "failed") else "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("nudge", nudge_node)
    g.add_conditional_edges(START, entry_router, {"agent": "agent", "tools": "tools"})
    g.add_conditional_edges("agent", after_agent, {"tools": "tools", "nudge": "nudge", END: END})
    g.add_conditional_edges("nudge", after_nudge, {"agent": "agent", END: END})
    g.add_conditional_edges("tools", after_tools, {"agent": "agent", END: END})
    return g.compile()
