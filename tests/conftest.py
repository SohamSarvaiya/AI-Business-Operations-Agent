from datetime import date
from decimal import Decimal

import pytest

from app.config import Settings
from app.db import Base, make_engine, set_engine, write_session
from app.llm.base import LLMClient, LLMResponse, ToolCall
from app.models import Customer, Order, OrderItem, Product


def make_settings(**overrides) -> Settings:
    base = dict(database_url="sqlite://", llm_provider="mock", today_override="2026-10-15",
                llm_retry_backoff_seconds=0.0, _env_file=None)
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def settings():
    return make_settings()


@pytest.fixture()
def engine():
    eng = make_engine("sqlite://")
    set_engine(eng)
    from app import models  # noqa: F401
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    set_engine(None)


@pytest.fixture()
def sample_data(engine):
    """Previous period 2026-09-01..15 vs current 2026-10-01..15 (hand-computable numbers)."""
    with write_session() as s:
        p1 = Product(sku="P1", name="Laptop Stand", category="Office", price=Decimal("1000"), stock_quantity=50, reorder_level=10)
        p2 = Product(sku="P2", name="Webcam", category="Electronics", price=Decimal("2000"), stock_quantity=5, reorder_level=10)
        p3 = Product(sku="P3", name="Notebook", category="Office", price=Decimal("100"), stock_quantity=500, reorder_level=100)
        p4 = Product(sku="P4", name="Old Mouse", category="Electronics", price=Decimal("500"), stock_quantity=20, reorder_level=5)
        c = Customer(name="Acme", region="North")
        s.add_all([p1, p2, p3, p4, c])
        s.flush()

        def order(day, status, items):
            o = Order(customer_id=c.id, order_date=day, status=status)
            s.add(o)
            s.flush()
            for p, qty in items:
                s.add(OrderItem(order_id=o.id, product_id=p.id, quantity=qty, unit_price=p.price))

        order(date(2026, 9, 5), "completed", [(p1, 10), (p2, 5)])      # 20,000
        order(date(2026, 9, 10), "completed", [(p3, 100), (p4, 10)])   # 15,000
        order(date(2026, 10, 5), "completed", [(p1, 4), (p2, 8)])      # 20,000
        order(date(2026, 10, 10), "completed", [(p3, 100)])            # 10,000
        order(date(2026, 10, 12), "cancelled", [(p1, 1)])              # ignored
    return engine


class ScriptedLLM(LLMClient):
    """Plays back a fixed list of responses (or callables) - deterministic agent tests."""
    provider = "scripted"
    model = "test"

    def __init__(self, steps, default=None):
        self.steps, self.default, self.calls = list(steps), default, []

    def chat(self, system, messages, tools):
        self.calls.append([dict(m) for m in messages])
        step = self.steps.pop(0) if self.steps else self.default
        if step is None:
            raise AssertionError("ScriptedLLM ran out of steps")
        step = step(messages) if callable(step) else step
        if isinstance(step, Exception):
            raise step
        return step


def call(name, args=None, id="c1"):
    return LLMResponse(tool_calls=[ToolCall(id=id, name=name, arguments=args or {})])


VALID_REPORT = {
    "title": "Test report", "period": "2026-10-01 to 2026-10-15", "executive_summary": "Summary.",
    "key_metrics": [{"name": "Revenue", "value": "30,000"}],
    "declining_products": [], "insights": ["i"], "recommendations": ["r"],
}
