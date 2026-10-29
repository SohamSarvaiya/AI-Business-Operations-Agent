"""Runs the graph and persists runs + tool logs in PostgreSQL."""
from uuid import uuid4

from sqlalchemy import func, select

from app.agent.graph import build_graph
from app.config import Settings, get_settings
from app.db import readonly_session, write_session
from app.llm.factory import get_llm_client
from app.models import AgentRun, ToolLog
from app.reporting import render_markdown
from app.tools import build_registry


class RunNotFound(Exception):
    pass


class RunStateError(Exception):
    pass


class AgentService:
    def __init__(self, settings: Settings | None = None, llm_factory=None):
        self.settings = settings or get_settings()
        self.llm_factory = llm_factory or (
            lambda provider=None, api_key=None, model=None: get_llm_client(provider, self.settings, api_key=api_key, model=model))

    def _make_llm(self, provider, api_key=None, model=None):
        # The API key lives only in memory for this call - it is never written to the DB, state or logs.
        if api_key or model:
            return self.llm_factory(provider, api_key=api_key, model=model)
        return self.llm_factory(provider)

    # ---- public API ----
    def start_run(self, request: str, provider: str | None = None, api_key: str | None = None,
                  model: str | None = None) -> dict:
        llm = self._make_llm(provider, api_key, model)
        run_id = uuid4().hex
        state = {"run_id": run_id, "request": request, "messages": [{"role": "user", "content": request}],
                 "pending_calls": [], "approval": None, "tool_logs": [], "report": None,
                 "status": "running", "error": None, "iterations": 0, "nudges": 0}
        with write_session() as s:
            s.add(AgentRun(id=run_id, request=request, provider=llm.provider, model=llm.model, status="running", state=state))
        return self._execute(run_id, llm, state)

    def resume_run(self, run_id: str, approve: bool, api_key: str | None = None) -> dict:
        with readonly_session() as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                raise RunNotFound(run_id)
            if run.status != "awaiting_approval":
                raise RunStateError(f"Run is '{run.status}', not awaiting approval.")
            state, provider, model = dict(run.state), run.provider, run.model
        state["approval"] = "approved" if approve else "rejected"
        llm = self._make_llm(provider, api_key, model if api_key else None)
        return self._execute(run_id, llm, state)

    def get_run(self, run_id: str) -> dict:
        with readonly_session() as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                raise RunNotFound(run_id)
            state = run.state or {}
            registry = build_registry(self.settings)
            pending = [
                {"tool": c["name"], "arguments": c["arguments"]}
                for c in state.get("pending_calls", [])
                if registry.get(c["name"]) and registry.get(c["name"]).requires_approval
            ] if run.status == "awaiting_approval" else []
            return {
                "run_id": run.id, "request": run.request, "status": run.status, "provider": run.provider, "model": run.model,
                "report": run.report, "report_markdown": render_markdown(run.report) if run.report else None,
                "pending_approvals": pending, "error": run.error, "tool_logs": state.get("tool_logs", []),
            }

    def get_logs(self, run_id: str) -> list[dict]:
        with readonly_session() as s:
            if s.get(AgentRun, run_id) is None:
                raise RunNotFound(run_id)
            rows = s.scalars(select(ToolLog).where(ToolLog.run_id == run_id).order_by(ToolLog.id))
            return [{"tool": r.tool, "arguments": r.arguments, "status": r.status, "approval": r.approval,
                     "duration_ms": r.duration_ms, "result_preview": r.result_preview, "sources": r.sources,
                     "error": r.error, "created_at": r.created_at.isoformat()} for r in rows]

    # ---- internals ----
    def _execute(self, run_id: str, llm, state: dict) -> dict:
        graph = build_graph(llm, build_registry(self.settings), self.settings)
        try:
            final = graph.invoke(state, config={"recursion_limit": 100})
        except Exception as exc:  # never leave a run stuck in "running"
            final = {**state, "status": "failed", "error": f"Graph error: {type(exc).__name__}: {exc}"}
        self._persist(run_id, final)
        return self.get_run(run_id)

    def _persist(self, run_id: str, final: dict) -> None:
        with write_session() as s:
            run = s.get(AgentRun, run_id)
            run.state = dict(final)
            run.status = final.get("status", "failed")
            run.report = final.get("report")
            run.error = final.get("error")
            already = s.scalar(select(func.count(ToolLog.id)).where(ToolLog.run_id == run_id)) or 0
            for log in final.get("tool_logs", [])[already:]:
                s.add(ToolLog(run_id=run_id, tool=log["tool"], arguments=log["arguments"], status=log["status"],
                              approval=log.get("approval"), duration_ms=log.get("duration_ms", 0.0),
                              result_preview=log.get("result_preview", ""), sources=log.get("sources", []), error=log.get("error")))
