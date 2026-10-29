"""Business tools. All SQL is parameterised and written by us - the LLM never writes SQL."""
import calendar
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models import Order, OrderItem, Product, RestockDraft
from app.tools import analytics
from app.tools.base import ToolError, ToolResult

REVENUE = func.sum(OrderItem.quantity * OrderItem.unit_price)


def _src(tables: list[str], detail: str) -> dict:
    return {"source_type": "database", "tables": tables, "detail": detail}


def _py_src(detail: str) -> dict:
    return {"source_type": "python", "tables": [], "detail": detail}


def _range(start: str, end: str) -> tuple[date, date]:
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ToolError("Dates must use YYYY-MM-DD format.")
    if s > e:
        raise ToolError("start_date must be on or before end_date.")
    return s, e


# ---------- argument models ----------
class DateRangeArgs(BaseModel):
    start_date: str = Field(description="YYYY-MM-DD, inclusive")
    end_date: str = Field(description="YYYY-MM-DD, inclusive")


class ProductSalesArgs(DateRangeArgs):
    limit: int = Field(10, ge=1, le=100, description="Max number of products")
    category: str = Field("", description="Optional category filter; empty = all")


class DecliningArgs(BaseModel):
    current_start: str = Field(description="YYYY-MM-DD")
    current_end: str = Field(description="YYYY-MM-DD")
    previous_start: str = Field(description="YYYY-MM-DD")
    previous_end: str = Field(description="YYYY-MM-DD")
    min_decline_pct: float = Field(5.0, ge=0, le=100, description="Minimum revenue drop in percent")


class InventoryArgs(BaseModel):
    low_stock_only: bool = Field(True, description="Only products at/below reorder level")


class GrowthArgs(BaseModel):
    current: float
    previous: float


class DateRangesArgs(BaseModel):
    reference_date: str = Field("", description="Optional YYYY-MM-DD; empty = today")


class RestockArgs(BaseModel):
    sku: str
    quantity: int = Field(ge=1, le=10000)
    reason: str = Field(description="Why this restock is needed")


# ---------- handlers ----------
def date_ranges(today: date) -> dict:
    month_start = today.replace(day=1)
    last_end = month_start - timedelta(days=1)
    last_start = last_end.replace(day=1)
    same_days_end = last_start + timedelta(days=min(today.day, calendar.monthrange(last_start.year, last_start.month)[1]) - 1)

    def f(a, b):
        return {"start_date": a.isoformat(), "end_date": b.isoformat()}

    return {
        "today": today.isoformat(),
        "this_month_to_date": f(month_start, today),
        "last_month_full": f(last_start, last_end),
        "last_month_same_days": f(last_start, same_days_end),
        "note": "For fair comparison use this_month_to_date vs last_month_same_days.",
    }


def make_date_ranges_handler(settings):
    def handler(_session, args: DateRangesArgs) -> ToolResult:
        ref = args.reference_date or settings.today_override
        try:
            today = date.fromisoformat(ref) if ref else date.today()
        except ValueError:
            raise ToolError("reference_date must use YYYY-MM-DD format.")
        return ToolResult(date_ranges(today), [_py_src("calendar arithmetic (no database access)")])

    return handler


def _product_rows(session, s: date, e: date, category: str = "") -> list[dict]:
    stmt = (
        select(
            Product.sku, Product.name, Product.category,
            func.sum(OrderItem.quantity).label("units"),
            REVENUE.label("revenue"),
            func.count(func.distinct(Order.id)).label("orders"),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == "completed", Order.order_date.between(s, e))
        .group_by(Product.id, Product.sku, Product.name, Product.category)
        .order_by(REVENUE.desc())
    )
    if category:
        stmt = stmt.where(func.lower(Product.category) == category.lower())
    return [
        {"sku": r.sku, "name": r.name, "category": r.category, "units": int(r.units or 0),
         "revenue": round(float(r.revenue or 0), 2), "orders": int(r.orders)}
        for r in session.execute(stmt)
    ]


def get_sales_summary(session, args: DateRangeArgs) -> ToolResult:
    s, e = _range(args.start_date, args.end_date)
    row = session.execute(
        select(func.count(func.distinct(Order.id)), func.coalesce(func.sum(OrderItem.quantity), 0), func.coalesce(REVENUE, 0))
        .select_from(Order).join(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.status == "completed", Order.order_date.between(s, e))
    ).one()
    orders, units, revenue = int(row[0]), int(row[1]), round(float(row[2]), 2)
    data = {
        "period": f"{s} to {e}", "total_revenue": revenue, "total_orders": orders, "units_sold": units,
        "average_order_value": round(revenue / orders, 2) if orders else None,
    }
    return ToolResult(data, [_src(["orders", "order_items"], f"completed orders {s}..{e}")])


def get_product_sales(session, args: ProductSalesArgs) -> ToolResult:
    s, e = _range(args.start_date, args.end_date)
    rows = _product_rows(session, s, e, args.category)[: args.limit]
    return ToolResult({"period": f"{s} to {e}", "products": rows},
                      [_src(["products", "orders", "order_items"], f"product sales {s}..{e}")])


def get_category_sales(session, args: DateRangeArgs) -> ToolResult:
    s, e = _range(args.start_date, args.end_date)
    agg: dict[str, dict] = {}
    for r in _product_rows(session, s, e):
        c = agg.setdefault(r["category"], {"category": r["category"], "revenue": 0.0, "units": 0})
        c["revenue"] = round(c["revenue"] + r["revenue"], 2)
        c["units"] += r["units"]
    cats = sorted(agg.values(), key=lambda c: -c["revenue"])
    return ToolResult({"period": f"{s} to {e}", "categories": cats},
                      [_src(["products", "orders", "order_items"], f"category sales {s}..{e}")])


def find_declining_products(session, args: DecliningArgs) -> ToolResult:
    cs, ce = _range(args.current_start, args.current_end)
    ps, pe = _range(args.previous_start, args.previous_end)
    rows = analytics.compare_products(_product_rows(session, cs, ce), _product_rows(session, ps, pe))
    dec = analytics.declining(rows, args.min_decline_pct)
    data = {
        "current_period": f"{cs} to {ce}", "previous_period": f"{ps} to {pe}",
        "min_decline_pct": args.min_decline_pct, "declining_count": len(dec), "declining_products": dec,
    }
    return ToolResult(data, [
        _src(["products", "orders", "order_items"], f"revenue per product for {cs}..{ce} and {ps}..{pe}"),
        _py_src("analytics.compare_products / analytics.declining"),
    ])


def get_inventory_status(session, args: InventoryArgs) -> ToolResult:
    stmt = select(Product).order_by((Product.stock_quantity - Product.reorder_level), Product.sku)
    if args.low_stock_only:
        stmt = stmt.where(Product.stock_quantity <= Product.reorder_level)
    items = [
        {"sku": p.sku, "name": p.name, "stock_quantity": p.stock_quantity, "reorder_level": p.reorder_level,
         "shortfall": max(0, p.reorder_level - p.stock_quantity)}
        for p in session.scalars(stmt)
    ]
    return ToolResult({"low_stock_only": args.low_stock_only, "items": items}, [_src(["products"], "current stock levels")])


def calculate_percentage_change(_session, args: GrowthArgs) -> ToolResult:
    return ToolResult({"current": args.current, "previous": args.previous,
                       "change_pct": analytics.pct_change(args.current, args.previous)},
                      [_py_src("analytics.pct_change")])


def create_restock_draft(session, args: RestockArgs) -> ToolResult:
    product = session.scalar(select(Product).where(Product.sku == args.sku))
    if product is None:
        raise ToolError(f"Unknown SKU '{args.sku}'.")
    draft = RestockDraft(product_id=product.id, quantity=args.quantity, reason=args.reason, status="draft")
    session.add(draft)
    session.flush()
    return ToolResult({"draft_id": draft.id, "sku": args.sku, "quantity": args.quantity, "status": "draft"},
                      [_src(["restock_drafts"], "inserted restock draft (needs separate purchasing approval)")])
