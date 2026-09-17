"""
Procurement Agent
=================
Decides what to reorder, how much, and how urgently.

The Forecast Agent answers "when will this run out". That is a prediction, not a
decision. This agent turns it into one: it combines what is on hand, the reorder
level a manager set, how fast the product actually moves and how long a
replacement takes to arrive, and proposes an order quantity with a reason.

Method
------
A classical reorder-point model, which is the right amount of machinery for the
data a warehouse of this size actually has:

    reorder point = (average daily demand x lead time) + safety stock
    order quantity = cover for the review period, rounded to a sensible pack

Safety stock uses the observed variability of demand rather than a flat
percentage, so an erratic product carries more cover than a steady one.
"""

import math

import db
from agents.base import Agent, Decision, ACCEPT, FLAG, INFO, register

#: Assumed days between placing an order and receiving it, when nothing better
#: is known. Overridable per product from settings later.
DEFAULT_LEAD_TIME_DAYS = 7
#: How many days of stock a single order should cover.
REVIEW_PERIOD_DAYS = 30
#: Service level as a z-score. 1.65 is the 95th percentile — the usual choice
#: for stock that is inconvenient but not dangerous to run out of.
SERVICE_Z = 1.65


@register
class ProcurementAgent(Agent):
    name = "Procurement Agent"
    role = "Decides what to reorder and how much, from demand and lead time."
    method = "reorder-point model with demand-variability safety stock"
    layer = "planning"

    def decide(self, context):
        lead_time = int(context.get("lead_time_days") or DEFAULT_LEAD_TIME_DAYS)
        only = context.get("product")

        inventory = db.inventory_summary()["rows"]
        if only:
            inventory = [r for r in inventory if r["name"] == only]

        demand = self._demand_by_product()
        proposals = []
        for row in inventory:
            p = self._evaluate(row, demand.get(row["name"], []), lead_time)
            if p:
                proposals.append(p)

        proposals.sort(key=lambda p: (-p["urgency"], p["days_cover"]))

        urgent = [p for p in proposals if p["priority"] == "urgent"]
        d = Decision(self.name,
                     FLAG if urgent else (ACCEPT if proposals else INFO),
                     method=self.method)
        d.data = {
            "proposals": proposals,
            "urgent": len(urgent),
            "lead_time_days": lead_time,
            "total_lines": len(proposals),
        }

        if not proposals:
            d.note("Nothing needs reordering: every product is above its "
                   "reorder point for the current demand.")
            d.confidence = 0.9
            return d

        d.confidence = round(
            sum(p["confidence"] for p in proposals) / len(proposals), 2)
        d.note("%d product(s) are at or below their reorder point."
               % len(proposals))
        if urgent:
            d.note("%d need attention now: %s."
                   % (len(urgent), ", ".join(p["name"] for p in urgent[:4])))
        for p in proposals[:5]:
            d.note("%s — %d on hand, %s cover; order %d. %s"
                   % (p["name"], p["on_hand"],
                      ("%.1f days" % p["days_cover"]) if p["days_cover"] < 999 else "no measured demand",
                      p["order_qty"], p["reason"]))
        return d

    # -- per-product evaluation ------------------------------------------
    def _evaluate(self, row, out_days, lead_time):
        name = row["name"]
        on_hand = row["qty"]
        min_qty = row.get("min_qty") or 0

        daily, variability, days_observed = self._demand_stats(out_days)

        # With no measured demand the only signal is the manager's own reorder
        # level. Respect it, and say plainly that there is no forecast behind it.
        if daily <= 0:
            if min_qty > 0 and on_hand <= min_qty:
                return {
                    "name": name,
                    "category": row.get("category") or "Uncategorised",
                    "on_hand": on_hand,
                    "reorder_point": min_qty,
                    "order_qty": max(min_qty * 2 - on_hand, 1),
                    "days_cover": 999.0,
                    "avg_daily_demand": 0.0,
                    "safety_stock": 0,
                    "priority": "normal",
                    "urgency": 0.4 if on_hand else 0.75,
                    "confidence": 0.4,
                    "reason": ("At or below the reorder level you set. No "
                               "consumption history yet, so this is your "
                               "threshold rather than a forecast."),
                }
            return None

        safety = int(math.ceil(SERVICE_Z * variability * math.sqrt(max(lead_time, 1))))
        computed_point = int(math.ceil(daily * lead_time)) + safety
        # A manager's explicit level is a floor, never something to be talked
        # down by a model.
        reorder_point = max(computed_point, min_qty)
        days_cover = on_hand / daily if daily else 999.0

        if on_hand > reorder_point:
            return None

        target = int(math.ceil(daily * (lead_time + REVIEW_PERIOD_DAYS))) + safety
        order_qty = max(target - on_hand, 1)

        if on_hand == 0:
            priority, urgency = "urgent", 1.0
        elif days_cover <= lead_time:
            priority, urgency = "urgent", 0.9
        elif days_cover <= lead_time * 1.5:
            priority, urgency = "soon", 0.65
        else:
            priority, urgency = "normal", 0.4

        # Confidence rises with the length of the history behind the estimate.
        confidence = round(min(0.95, 0.4 + 0.05 * days_observed), 2)

        if on_hand == 0:
            reason = ("Out of stock. At %.2f/day it should have been reordered "
                      "%d days ago." % (daily, lead_time))
        elif days_cover <= lead_time:
            reason = ("Only %.1f days of cover against a %d-day lead time — it "
                      "will run out before a delivery arrives." % (days_cover, lead_time))
        else:
            reason = ("%.1f days of cover, at or under the reorder point of %d "
                      "(%d for lead time + %d safety stock)."
                      % (days_cover, reorder_point,
                         int(math.ceil(daily * lead_time)), safety))

        return {
            "name": name,
            "category": row.get("category") or "Uncategorised",
            "on_hand": on_hand,
            "reorder_point": reorder_point,
            "order_qty": order_qty,
            "days_cover": round(days_cover, 1),
            "avg_daily_demand": round(daily, 3),
            "safety_stock": safety,
            "priority": priority,
            "urgency": urgency,
            "confidence": confidence,
            "reason": reason,
        }

    # -- demand history ---------------------------------------------------
    def _demand_by_product(self):
        """OUT events grouped by product, as counts per calendar day."""
        out = {}
        for h in db.out_history():
            name = h.get("name")
            if not name:
                continue
            day = (h.get("ts") or "")[:10]
            out.setdefault(name, {})
            out[name][day] = out[name].get(day, 0) + 1
        return {name: sorted(days.items()) for name, days in out.items()}

    def _demand_stats(self, out_days):
        """Mean and standard deviation of daily demand.

        Days with no movement count as zero. Leaving them out would make an
        intermittent product look like a fast, steady one and undersize its
        safety stock — the classic way a reorder model quietly fails.
        """
        if not out_days:
            return 0.0, 0.0, 0

        from datetime import date
        days = {d: n for d, n in out_days}
        try:
            first = date.fromisoformat(min(days))
            last = date.fromisoformat(max(days))
        except ValueError:
            return 0.0, 0.0, 0

        span = (last - first).days + 1
        series = []
        for i in range(span):
            d = date.fromordinal(first.toordinal() + i).isoformat()
            series.append(days.get(d, 0))

        n = len(series)
        mean = sum(series) / n
        if n < 2:
            return mean, 0.0, n
        var = sum((x - mean) ** 2 for x in series) / (n - 1)
        return mean, math.sqrt(var), n

    def fallback(self, context, error):
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"proposals": [], "urgent": 0, "total_lines": 0}
        d.note("Reorder planning is unavailable (%s)." % error.__class__.__name__)
        d.note("Low-stock alerts from the reorder levels you set are unaffected.")
        return d
