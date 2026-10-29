import json

import pytest
from sqlalchemy import func, select

from app.agent.service import AgentService, RunStateError
from app.db import readonly_session
from app.models import RestockDraft, ToolLog
from tests.conftest import VALID_REPORT, ScriptedLLM, call, make_settings

SUMMARY_ARGS = {"start_date": "2026-10-01", "end_date": "2026-10-15"}


def svc(llm, **settings):
    return AgentService(make_settings(**settings), llm_factory=lambda provider=None: llm)


def test_happy_path_with_sources_and_logs(sample_data):
    llm = ScriptedLLM([call("get_sales_summary", SUMMARY_ARGS), call("submit_report", VALID_REPORT)])
    run = svc(llm).start_run("sales report")
    assert run["status"] == "completed"
    sources = run["report"]["data_sources"]
    assert sources and sources[0]["tool"] == "get_sales_summary" and "orders" in sources[0]["tables"]
    assert [l["tool"] for l in run["tool_logs"]] == ["get_sales_summary", "submit_report"]
    assert "## Data sources" in run["report_markdown"]
    with readonly_session() as s:
        assert s.scalar(select(func.count(ToolLog.id))) == 2


def test_llm_cannot_fake_data_sources(sample_data):
    fake = {**VALID_REPORT, "data_sources": [{"tool": "x", "source_type": "database", "tables": ["secret"]}]}
    run = svc(ScriptedLLM([call("submit_report", fake)])).start_run("r")
    assert run["report"]["data_sources"] == []          # system fills sources from real tool logs only


def test_invalid_report_is_retried(sample_data):
    llm = ScriptedLLM([call("submit_report", {"title": "only title"}), call("submit_report", VALID_REPORT)])
    run = svc(llm).start_run("r")
    assert run["status"] == "completed"
    assert run["tool_logs"][0]["status"] == "error"
    assert json.loads(llm.calls[1][-1]["content"])["ok"] is False   # LLM saw the validation error


def test_tool_error_is_fed_back_and_recovered(sample_data):
    llm = ScriptedLLM([call("get_sales_summary", {"start_date": "bad", "end_date": "bad"}),
                       call("get_sales_summary", SUMMARY_ARGS, id="c2"), call("submit_report", VALID_REPORT, id="c3")])
    run = svc(llm).start_run("r")
    assert run["status"] == "completed"
    assert [l["status"] for l in run["tool_logs"]] == ["error", "ok", "ok"]


def test_text_only_reply_is_nudged(sample_data):
    from app.llm.base import LLMResponse
    llm = ScriptedLLM([LLMResponse(text="Here is my answer in prose"), call("submit_report", VALID_REPORT)])
    run = svc(llm).start_run("r")
    assert run["status"] == "completed"
    assert "submit_report" in llm.calls[1][-1]["content"]


def test_max_iterations_guard(sample_data):
    llm = ScriptedLLM([], default=call("get_inventory_status"))
    run = svc(llm, max_iterations=3).start_run("loop forever")
    assert run["status"] == "failed" and "max_iterations" in run["error"]


def test_llm_failure_is_reported_not_raised(sample_data):
    llm = ScriptedLLM([], default=RuntimeError("rate limited"))
    run = svc(llm, llm_max_retries=2).start_run("r")
    assert run["status"] == "failed" and "rate limited" in run["error"]
    assert len(llm.calls) == 2                                     # retried


def test_approval_flow_approve(sample_data):
    args = {"sku": "P2", "quantity": 20, "reason": "low stock"}
    llm = ScriptedLLM([call("create_restock_draft", args), call("submit_report", VALID_REPORT, id="c2")])
    service = svc(llm, enable_write_tools=True)
    run = service.start_run("restock webcams")
    assert run["status"] == "awaiting_approval"
    assert run["pending_approvals"][0]["tool"] == "create_restock_draft"
    with readonly_session() as s:
        assert s.scalar(select(func.count(RestockDraft.id))) == 0   # nothing written before approval
    run = service.resume_run(run["run_id"], approve=True)
    assert run["status"] == "completed"
    with readonly_session() as s:
        assert s.scalar(select(func.count(RestockDraft.id))) == 1
    assert run["tool_logs"][0]["approval"] == "approved"
    with pytest.raises(RunStateError):
        service.resume_run(run["run_id"], approve=True)             # cannot approve twice


def test_approval_flow_reject(sample_data):
    llm = ScriptedLLM([call("create_restock_draft", {"sku": "P2", "quantity": 20, "reason": "x"}),
                       call("submit_report", VALID_REPORT, id="c2")])
    service = svc(llm, enable_write_tools=True)
    run = service.start_run("restock")
    run = service.resume_run(run["run_id"], approve=False)
    assert run["status"] == "completed"
    assert run["tool_logs"][0]["status"] == "rejected"
    with readonly_session() as s:
        assert s.scalar(select(func.count(RestockDraft.id))) == 0


def test_write_tool_unavailable_by_default(sample_data):
    llm = ScriptedLLM([call("create_restock_draft", {"sku": "P2", "quantity": 5, "reason": "x"}),
                       call("submit_report", VALID_REPORT, id="c2")])
    run = svc(llm).start_run("restock")
    assert run["status"] == "completed"                              # no approval gate: tool simply does not exist
    assert run["tool_logs"][0]["status"] == "error" and "Unknown tool" in run["tool_logs"][0]["error"]
    with readonly_session() as s:
        assert s.scalar(select(func.count(RestockDraft.id))) == 0
