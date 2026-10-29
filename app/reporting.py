def render_markdown(report: dict) -> str:
    lines = [f"# {report['title']}", f"**Period:** {report['period']}", "", "## Executive summary", report["executive_summary"], ""]
    if report.get("key_metrics"):
        lines += ["## Key metrics", "| Metric | Value | Context |", "|---|---|---|"]
        lines += [f"| {m['name']} | {m['value']} | {m.get('context', '')} |" for m in report["key_metrics"]]
        lines.append("")
    if report.get("declining_products"):
        lines += ["## Declining products", "| SKU | Product | Previous | Current | Change % |", "|---|---|---|---|---|"]
        lines += [
            f"| {p['sku']} | {p['name']} | {p['previous_revenue']:,.2f} | {p['current_revenue']:,.2f} | {p['change_pct']:.1f}% |"
            for p in report["declining_products"]
        ]
        lines.append("")
    for heading, key in (("Insights", "insights"), ("Recommendations", "recommendations"), ("Limitations", "limitations")):
        if report.get(key):
            lines += [f"## {heading}"] + [f"- {x}" for x in report[key]] + [""]
    if report.get("data_sources"):
        lines.append("## Data sources")
        for s in report["data_sources"]:
            tables = ", ".join(s.get("tables", [])) or "-"
            lines.append(f"- `{s['tool']}` ({s['source_type']}): {tables} — {s.get('detail', '')}")
    return "\n".join(lines)
