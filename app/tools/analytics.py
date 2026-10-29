"""Pure Python calculations. The LLM never does arithmetic itself."""


def pct_change(current: float, previous: float) -> float | None:
    """Percent change; None when the previous value is 0 (undefined)."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def compare_products(current_rows: list[dict], previous_rows: list[dict]) -> list[dict]:
    cur = {r["sku"]: r for r in current_rows}
    prev = {r["sku"]: r for r in previous_rows}
    result = []
    for sku in sorted(set(cur) | set(prev)):
        c, p = cur.get(sku), prev.get(sku)
        base = p or c
        cur_rev, prev_rev = (c["revenue"] if c else 0.0), (p["revenue"] if p else 0.0)
        cur_units, prev_units = (c["units"] if c else 0), (p["units"] if p else 0)
        result.append(
            {
                "sku": sku,
                "name": base["name"],
                "category": base["category"],
                "previous_revenue": round(prev_rev, 2),
                "current_revenue": round(cur_rev, 2),
                "revenue_change": round(cur_rev - prev_rev, 2),
                "revenue_change_pct": pct_change(cur_rev, prev_rev),
                "previous_units": prev_units,
                "current_units": cur_units,
                "units_change_pct": pct_change(cur_units, prev_units),
            }
        )
    return result


def declining(rows: list[dict], min_decline_pct: float = 0.0) -> list[dict]:
    """Products whose revenue fell by at least min_decline_pct; biggest absolute drop first."""
    out = [
        r for r in rows
        if r["previous_revenue"] > 0
        and r["revenue_change_pct"] is not None
        and r["revenue_change_pct"] < 0
        and -r["revenue_change_pct"] >= min_decline_pct
    ]
    return sorted(out, key=lambda r: r["revenue_change"])
