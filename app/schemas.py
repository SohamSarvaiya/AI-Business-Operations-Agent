"""Structured output of the agent (validated with Pydantic)."""
from pydantic import BaseModel, Field


class Metric(BaseModel):
    name: str = Field(description="Metric name, e.g. 'Total revenue'")
    value: str = Field(description="Formatted value taken from tool results")
    context: str = Field("", description="Comparison / explanation, e.g. '-12.4% vs previous period'")


class DecliningProduct(BaseModel):
    sku: str
    name: str
    previous_revenue: float
    current_revenue: float
    change_pct: float = Field(0.0, description="Revenue change in percent (negative = decline)")
    note: str = Field("", description="Optional short explanation")


class ReportSubmission(BaseModel):
    """Final business report. Every number must come from tool results."""
    title: str
    period: str = Field(description="Analysed period and comparison period")
    executive_summary: str
    key_metrics: list[Metric]
    declining_products: list[DecliningProduct] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list, description="Missing data, assumptions, caveats")


class DataSource(BaseModel):
    tool: str
    source_type: str
    tables: list[str] = Field(default_factory=list)
    detail: str = ""


class BusinessReport(ReportSubmission):
    """Report + data sources. Sources are filled by the system from tool logs, not by the LLM."""
    data_sources: list[DataSource] = Field(default_factory=list)
