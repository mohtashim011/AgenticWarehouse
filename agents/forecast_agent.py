"""
Forecast Agent
==============
Predicts when a product will run out of stock, from its consumption history.
Uses the OUT-scan log to estimate an average daily out-rate, then divides the
current on-hand quantity by that rate. A simple, transparent forecasting model
(moving-average style) — the seed of the demand-forecasting an intelligent
warehouse needs.
"""

from collections import Counter
from datetime import datetime

import db
from agents.base import Agent, Decision, ACCEPT, FLAG, INFO, register


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


@register
class ForecastAgent(Agent):
    name = "Forecast Agent"
    role = "Predicts when a product will run out, from its consumption history."
    method = "moving-average consumption rate"
    layer = "planning"

    def decide(self, context):
        result = _forecast(context.get("name"))
        days = result.get("days_to_stockout")
        below = result.get("below_reorder")
        verdict = FLAG if (below or (days is not None and days < 3)) else (
            ACCEPT if days is not None else INFO)
        # Confidence in a forecast is confidence in its history: one OUT event
        # is not a demand curve.
        confidence = 0.0 if days is None else min(0.9, 0.3 + 0.1 * result.get("avg_daily_out", 0))
        d = Decision(self.name, verdict, confidence, result.get("notes", []),
                     method=self.method)
        d.data = {k: v for k, v in result.items() if k not in ("agent", "notes")}
        return d

    def fallback(self, context, error):
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"days_to_stockout": None, "avg_daily_out": 0.0,
                  "below_reorder": False}
        d.note("Forecasting is unavailable (%s)." % error.__class__.__name__)
        d.note("Stock movement was unaffected.")
        return d


def run(name):
    """Forecast one product, in the trace format the pipeline uses."""
    decision = ForecastAgent.instance.run({"name": name})
    out = decision.to_dict()
    out["agent"] = ForecastAgent.name
    out["notes"] = out.get("rationale", [])
    return out


def _forecast(name):
    if not name or name == "Unknown Item":
        return {
            "agent": "Forecast Agent",
            "name": name,
            "days_to_stockout": None,
            "avg_daily_out": 0.0,
            "notes": ["No named product to forecast."],
        }

    history = [h for h in db.out_history() if h["name"] == name]
    inv = db.inventory_summary()
    on_hand = next((r["qty"] for r in inv["rows"] if r["name"] == name), 0)

    # The reorder level is the user's own threshold — it fires regardless of
    # whether there is enough history to forecast anything.
    min_qty = db.min_qty_for(name)
    reorder_notes = []
    below_reorder = min_qty > 0 and on_hand <= min_qty
    if below_reorder:
        reorder_notes.append(
            "BELOW REORDER LEVEL — %d on hand, alert set at %d." % (on_hand, min_qty)
            if on_hand else "OUT OF STOCK — reorder level is %d." % min_qty
        )

    if len(history) < 1:
        return {
            "agent": "Forecast Agent",
            "name": name,
            "on_hand": on_hand,
            "min_qty": min_qty,
            "below_reorder": below_reorder,
            "days_to_stockout": None,
            "avg_daily_out": 0.0,
            "notes": reorder_notes + ["Not enough OUT history yet to forecast stock-out."],
        }

    times = [_parse(h["ts"]) for h in history if _parse(h["ts"])]
    times.sort()
    span_days = max((times[-1] - times[0]).total_seconds() / 86400.0, 1e-6) if len(times) > 1 else 1.0
    # Count OUTs per day; if all happened "today", treat the span as ~1 day.
    avg_daily_out = len(history) / max(span_days, 1.0)

    days = round(on_hand / avg_daily_out, 1) if avg_daily_out > 0 else None
    notes = list(reorder_notes)
    if days is not None:
        notes.append("At %.2f units/day, ~%s stock left." % (avg_daily_out, f"{days} days"))
        # Estimate when stock will cross the user's reorder level, not just zero.
        if min_qty > 0 and not below_reorder:
            to_reorder = round((on_hand - min_qty) / avg_daily_out, 1)
            notes.append("Hits its reorder level of %d in ~%s days." % (min_qty, to_reorder))
        if days < 3:
            notes.append("LOW STOCK WARNING — reorder soon.")
    return {
        "agent": "Forecast Agent",
        "name": name,
        "on_hand": on_hand,
        "min_qty": min_qty,
        "below_reorder": below_reorder,
        "avg_daily_out": round(avg_daily_out, 2),
        "days_to_stockout": days,
        "notes": notes,
    }
