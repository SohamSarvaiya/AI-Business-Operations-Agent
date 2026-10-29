import pytest
from fastapi.testclient import TestClient

from app.agent.service import AgentService
from app.api import get_service
from app.main import app
from tests.conftest import make_settings


@pytest.fixture()
def client(sample_data):
    settings = make_settings()
    app.dependency_overrides[get_service] = lambda: AgentService(settings)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health_and_tools(client):
    assert client.get("/health").json() == {"status": "ok"}
    tools = client.get("/tools").json()
    assert all(t["read_only"] for t in tools) and "submit_report" in [t["name"] for t in tools]


def test_run_report_and_logs(client):
    r = client.post("/runs", json={"request": "Prepare a sales report for this month and identify declining products"})
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "completed", run["error"]
    assert [p["sku"] for p in run["report"]["declining_products"]] == ["P1", "P4"]
    assert run["report"]["data_sources"]
    logs = client.get(f"/runs/{run['run_id']}/logs").json()
    assert logs[0]["tool"] == "get_date_ranges" and all("duration_ms" in l for l in logs)
    assert client.get(f"/runs/{run['run_id']}").json()["status"] == "completed"


def test_errors(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/approval", json={"approve": True}).status_code == 404
    assert client.post("/runs", json={"request": "x"}).status_code == 422
    r = client.post("/runs", json={"request": "sales report please", "provider": "openai"})
    assert r.status_code == 400 and "OPENAI_API_KEY" in r.json()["detail"]


def test_ui_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "AI Business Operations Agent" in r.text and "API key" in r.text


def test_api_key_override_is_used_but_never_persisted(sample_data):
    import json
    from sqlalchemy import select
    from app.db import readonly_session
    from app.models import AgentRun, ToolLog
    from tests.conftest import VALID_REPORT, ScriptedLLM, call

    seen = {}

    def factory(provider=None, api_key=None, model=None):
        seen.update(provider=provider, api_key=api_key, model=model)
        return ScriptedLLM([call("submit_report", VALID_REPORT)])

    run = AgentService(make_settings(), llm_factory=factory).start_run("report", "openai", "sk-SECRET-123", "gpt-x")
    assert seen == {"provider": "openai", "api_key": "sk-SECRET-123", "model": "gpt-x"}
    assert "sk-SECRET-123" not in json.dumps(run, default=str)
    with readonly_session() as s:
        dump = json.dumps([r.state for r in s.scalars(select(AgentRun))], default=str)
        dump += json.dumps([l.arguments for l in s.scalars(select(ToolLog))], default=str)
    assert "sk-SECRET-123" not in dump
