"""
Inventory Agent
===============
Owns the live stock state. Given a parsed item and a direction (IN / OUT), it
decides whether the action is valid and applies it to the database. This is the
autonomous "decision + action" step of the pipeline.

Stock is QUANTITY based: a product number is a SKU, not a single serial number,
so the same code can be scanned as many times as there are physical units.

Rules (a small state machine, exactly the kind of logic the research proposal
wants distributed across cooperating agents):
  IN  : always accept                        -> quantity + 1
  OUT : quantity > 0                         -> accept, quantity - 1
        item never seen / quantity already 0 -> reject (nothing to remove)
"""

import db
from agents.base import Agent, Decision, ACCEPT, REJECT, register


def _batch_label(batchno):
    return f" (batch {batchno})" if batchno else ""


@register
class InventoryAgent(Agent):
    name = "Inventory Agent"
    role = "Decides whether a stock movement is valid, and applies it."
    method = "quantity state machine with FIFO batch fallback"
    layer = "operations"
    # The one agent whose failure must not be swallowed: if the stock write
    # fails, reporting success would put the books out by a unit with nothing
    # to show for it.
    critical = True

    def decide(self, context):
        result = _apply(context["item"], context["mode"], context["category"])
        d = Decision(self.name,
                     ACCEPT if result["decision"] == "ACCEPT" else REJECT,
                     1.0, [result["reason"]], method=self.method)
        d.data = {k: v for k, v in result.items() if k != "agent"}
        return d


def run(item, mode, category):
    """Apply a stock movement, in the trace format the pipeline uses."""
    decision = InventoryAgent.instance.run(
        {"item": item, "mode": mode, "category": category})
    out = decision.to_dict()
    out["agent"] = InventoryAgent.name
    out["notes"] = out.get("rationale", [])
    return out


def _apply(item, mode, category):
    productno = item["productno"]
    name = item["name"]
    batchno = item.get("batchno") or ""

    if mode == "IN":
        saved = db.stock_in(name, batchno, productno, category, item.get("code", ""))
        total = saved["total"]
        return {
            "agent": "Inventory Agent",
            "decision": "ACCEPT",
            "action": "IN",
            "reason": (f"Added 1 x {name}{_batch_label(saved['batchno'])}. "
                       f"Quantity of {productno} is now {total}."),
            "applied": True,
            "qty": total,
            "batchno": saved["batchno"],
            "batch_qty": saved["qty"],
            "item": saved,
        }

    if mode == "OUT":
        on_hand = db.product_total(productno)
        if on_hand <= 0:
            seen = db.get_item(productno) is not None
            detail = "quantity is already 0" if seen else "it was never scanned in"
            return {
                "agent": "Inventory Agent",
                "decision": "REJECT",
                "action": "REJECT",
                "reason": f"Cannot remove {productno} — {detail}.",
                "applied": False,
                "qty": 0,
            }
        saved = db.stock_out(productno, batchno)
        total = saved["total"]
        # The scanned batch may have been empty, in which case the oldest batch
        # holding stock was drawn down instead — say so rather than hide it.
        drawn = saved["batchno"]
        note = ""
        if batchno and drawn != batchno:
            note = f" Batch {batchno} was empty, so batch {drawn or 'no-batch'} was used (FIFO)."
        return {
            "agent": "Inventory Agent",
            "decision": "ACCEPT",
            "action": "OUT",
            "reason": (f"Removed 1 x {name}{_batch_label(drawn)}. "
                       f"Quantity of {productno} is now {total}.{note}"),
            "applied": True,
            "qty": total,
            "batchno": drawn,
            "batch_qty": saved["qty"],
            "item": saved,
        }

    return {
        "agent": "Inventory Agent",
        "decision": "REJECT",
        "action": "REJECT",
        "reason": f"Unknown mode '{mode}'.",
        "applied": False,
    }
