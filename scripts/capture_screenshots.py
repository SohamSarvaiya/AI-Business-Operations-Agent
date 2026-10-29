"""Regenerate the README screenshots in docs/screenshots/.

    pip install -r requirements-dev.txt && playwright install chromium
    python scripts/capture_screenshots.py

What it does (no API key, no PostgreSQL needed):
  1. creates a throw-away SQLite DB and seeds the demo data for a FIXED date (2026-10-29),
     so the screenshots are deterministic and always show the same numbers;
  2. starts the real FastAPI app (same routes + same static UI) on a free local port;
  3. drives the UI with headless Chromium and saves one PNG per UI state.

The "Demo (no key)" model is the real built-in MockLLMClient. Only the approval screenshots use a
tiny scripted model, because the mock never asks for a write action. It calls the real
`create_restock_draft` tool, so the approval gate, DB write and tool log are all genuine.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.agent.service import AgentService  # noqa: E402
from app.api import get_service  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, set_engine  # noqa: E402
from app.llm.base import LLMClient, LLMResponse, ToolCall  # noqa: E402
from app.llm.factory import get_llm_client  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
DEMO_DAY = date(2026, 10, 29)
VIEWPORT = {"width": 1360, "height": 900}
SCALE = 1.5  # crisp on retina but keeps PNGs small


class ApprovalDemoLLM(LLMClient):
    """Scripted model: check low stock -> ask to create a restock draft -> write a short report."""
    provider = "scripted"
    model = "approval-demo"

    def chat(self, system, messages, tools):
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        names = [m["name"] for m in tool_msgs]
        if not tool_msgs:
            return self._call("get_inventory_status", {"low_stock_only": True})
        if "create_restock_draft" not in names:
            items = json.loads(tool_msgs[0]["content"])["data"]["items"]
            item = max(items, key=lambda i: i["shortfall"])  # the most urgent low-stock product
            return self._call("create_restock_draft", {
                "sku": item["sku"], "quantity": item["reorder_level"] * 2,
                "reason": f"Stock {item['stock_quantity']} is below reorder level {item['reorder_level']}."})
        draft = json.loads(tool_msgs[-1]["content"])
        items = json.loads(tool_msgs[0]["content"])["data"]["items"]
        if not draft.get("ok"):
            summary, metric = "The restock draft was rejected, so no data was changed.", "Rejected"
        else:
            d = draft["data"]
            summary = f"A restock draft #{d['draft_id']} for {d['quantity']} units of {d['sku']} was created after approval."
            metric = f"Draft #{d['draft_id']}"
        return self._call("submit_report", {
            "title": "Low-stock review", "period": "Current inventory snapshot",
            "executive_summary": summary,
            "key_metrics": [{"name": "Products below reorder level", "value": str(len(items)), "context": "from get_inventory_status"},
                            {"name": "Restock draft", "value": metric, "context": "needs separate purchasing approval"}],
            "insights": [f"{i['name']} ({i['sku']}): stock {i['stock_quantity']} vs reorder level {i['reorder_level']}." for i in items],
            "recommendations": ["Have purchasing review the draft before any order is placed."],
            "limitations": ["Only the inventory table was analysed."]})

    @staticmethod
    def _call(name, args):
        return LLMResponse(tool_calls=[ToolCall(id=f"demo_{name}", name=name, arguments=args)])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(db_file: Path, scripted: dict) -> tuple[uvicorn.Server, str]:
    set_engine(make_engine(f"sqlite:///{db_file}"))
    from app.db import init_db
    init_db()
    seed(reset=True, today=DEMO_DAY)

    settings = Settings(database_url=f"sqlite:///{db_file}", llm_provider="mock", enable_write_tools=True,
                        today_override=DEMO_DAY.isoformat(), _env_file=None)

    def llm_factory(provider=None, api_key=None, model=None):
        if scripted["on"] or provider == "scripted":
            return ApprovalDemoLLM()
        return get_llm_client(provider, settings, api_key=api_key, model=model)

    app.dependency_overrides[get_service] = lambda: AgentService(settings, llm_factory=llm_factory)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")
    return server, f"http://127.0.0.1:{port}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scripted = {"on": False}
    with tempfile.TemporaryDirectory() as tmp:
        server, base = start_server(Path(tmp) / "demo.db", scripted)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, color_scheme="light")
                page = ctx.new_page()
                shot = lambda name, **kw: page.screenshot(path=str(OUT / name), **kw)  # noqa: E731

                # 1) landing page, demo mode
                page.goto(base)
                page.wait_for_function("document.querySelector('#healthTxt').textContent === 'API online'")
                shot("01-home.png")

                # 2) other providers: API key panel (left empty on purpose)
                page.click("#providers button[data-p=anthropic]")
                shot("02-llm-settings.png", clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": 780})
                page.click("#providers button[data-p=mock]")

                # 3) full sales report (real MockLLMClient + real tools)
                page.click("#go")
                page.wait_for_selector(".badge.completed", timeout=60000)
                page.wait_for_selector("text=Tool execution log")
                shot("03-sales-report.png", full_page=True)

                # 4) tool execution log with the first calls expanded
                for d in page.query_selector_all("details")[:2]:
                    d.evaluate("e => e.open = true")
                log = page.locator(".card", has_text="Tool execution log").last
                log.scroll_into_view_if_needed()
                log.screenshot(path=str(OUT / "04-tool-log.png"))

                # 5) human approval gate (scripted model asks for a write action)
                scripted["on"] = True
                page.fill("#req", "Check low stock products and prepare a restock draft for the most urgent one.")
                page.click("#go")
                page.wait_for_selector(".badge.awaiting_approval", timeout=60000)
                shot("05-approval-required.png")

                # 6) after clicking Approve
                page.click("button.approve")
                page.wait_for_selector(".badge.completed", timeout=60000)
                for d in page.query_selector_all("details"):
                    d.evaluate("e => e.open = true")
                shot("06-approved-and-logged.png", full_page=True)
                browser.close()
        finally:
            server.should_exit = True
            app.dependency_overrides.clear()
            set_engine(None)
    print("Saved:", *sorted(p.name for p in OUT.glob("*.png")), sep="\n  ")


if __name__ == "__main__":
    main()
