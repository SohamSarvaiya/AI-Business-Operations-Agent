from pydantic import ValidationError

from app.db import readonly_session, write_session
from app.llm.base import ToolSpec
from app.schemas import ReportSubmission
from app.tools import sales
from app.tools.base import ToolDef, ToolError, ToolResult
from app.tools.schema import to_llm_schema

SUBMIT_REPORT = "submit_report"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(t.name, t.description, to_llm_schema(t.args_model)) for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}")
        try:
            args = tool.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            raise ToolError(f"Invalid arguments for {name}: {detail}")
        if not tool.needs_db:
            return tool.handler(None, args)
        scope = write_session if tool.mutating else readonly_session
        with scope() as session:
            return tool.handler(session, args)


def build_registry(settings) -> ToolRegistry:
    r = ToolRegistry()
    S = sales
    r.register(ToolDef("get_date_ranges", "Get calendar ranges (this month to date, last month, comparable period). Use for relative dates like 'this month'.",
                       S.DateRangesArgs, S.make_date_ranges_handler(settings), needs_db=False))
    r.register(ToolDef("get_sales_summary", "Total revenue, order count, units and average order value for completed orders in a date range.",
                       S.DateRangeArgs, S.get_sales_summary))
    r.register(ToolDef("get_product_sales", "Revenue and units per product in a date range, ranked by revenue.",
                       S.ProductSalesArgs, S.get_product_sales))
    r.register(ToolDef("get_category_sales", "Revenue and units per product category in a date range.",
                       S.DateRangeArgs, S.get_category_sales))
    r.register(ToolDef("find_declining_products", "Compare two periods and list products whose revenue declined (computed in Python). Use equal-length periods.",
                       S.DecliningArgs, S.find_declining_products))
    r.register(ToolDef("get_inventory_status", "Current stock levels; by default only products at or below reorder level.",
                       S.InventoryArgs, S.get_inventory_status))
    r.register(ToolDef("calculate_percentage_change", "Exact percentage change between two numbers. Use instead of mental math.",
                       S.GrowthArgs, S.calculate_percentage_change, needs_db=False))
    if settings.enable_write_tools:
        r.register(ToolDef("create_restock_draft", "Create a DRAFT restock request for a product. Requires human approval before it runs.",
                           S.RestockArgs, S.create_restock_draft, mutating=True, requires_approval=True))
    r.register(ToolDef(SUBMIT_REPORT, "Submit the final structured business report. Call exactly once when the analysis is complete.",
                       ReportSubmission,
                       lambda _s, _a: ToolResult({"accepted": True, "message": "Report accepted."}, []),
                       needs_db=False))
    return r
