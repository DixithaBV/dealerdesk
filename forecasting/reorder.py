"""Forecast + reorder maths (contract section 10). Django-free."""
import csv
import math
import statistics
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


@lru_cache(maxsize=4)
def load_forecast(ml_dir: str):
    out = defaultdict(dict)
    with open(Path(ml_dir) / "forecast.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            out[r["sku"]][r["week_start"]] = float(r["forecast_units"])
    return dict(out)


@lru_cache(maxsize=4)
def load_lead_times(data_dir: str):
    with open(Path(data_dir) / "lead_times.csv", newline="", encoding="utf-8-sig") as fh:
        return [(r["sku"], int(float(r["lead_time_weeks"]))) for r in csv.DictReader(fh)]


@lru_cache(maxsize=4)
def load_recent_sales(data_dir: str, n=12):
    rows = defaultdict(list)
    with open(Path(data_dir) / "sales_history.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows[r["sku"]].append((r["week_start"], float(r["units_sold"])))
    return {k: [u for _, u in sorted(v)][-n:] for k, v in rows.items()}


def sample_std(xs):
    return statistics.stdev(xs) if len(xs) >= 2 else 0.0


def reorder_entry(sku, lead_weeks, forecast_by_week, recent_units, current_stock):
    L = lead_weeks
    ltd = sum(forecast_by_week[w] for w in WEEKS[:L])
    safety = math.ceil(1.65 * sample_std(recent_units) * math.sqrt(L))
    rp = ltd + safety
    return {"sku": sku, "current_stock": current_stock, "lead_time_weeks": L,
            "lead_time_demand": round(ltd, 4), "safety_stock": safety, "reorder_point": round(rp, 4),
            "reorder_qty": max(0, math.ceil(rp - current_stock))}
