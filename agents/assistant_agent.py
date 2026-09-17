"""
Assistant Agent  (optional LLM layer)
=====================================
A natural-language "warehouse assistant" that answers questions about the live
inventory. If the Anthropic SDK and an ANTHROPIC_API_KEY are available it uses
Claude (claude-opus-4-8); otherwise it falls back to a local rule-based
responder so the MVP always works offline.

This is the only agent that talks to an external LLM, and it is entirely
optional — the scanning pipeline runs fully offline without it.
"""

import os
import json

import db
from agents.base import Agent, Decision, ACCEPT, register

MODEL = "claude-opus-4-8"


@register
class AssistantAgent(Agent):
    name = "Assistant Agent"
    role = "Answers plain-language questions about the live stock."
    method = "Claude when configured, otherwise a local rule-based responder"
    layer = "assistance"

    def decide(self, context):
        result = _answer(context.get("question", ""))
        d = Decision(self.name, ACCEPT,
                     0.9 if result.get("mode") == "claude" else 0.6,
                     method=("Claude %s" % MODEL) if result.get("mode") == "claude"
                            else "offline rule-based responder")
        d.data = result
        d.note("Answered %s." % ("using Claude" if result.get("mode") == "claude"
                                 else "offline, from live inventory data"))
        if result.get("note"):
            d.note(result["note"])
        return d

    def fallback(self, context, error):
        d = Decision(self.name, ACCEPT, 0.0, method="unavailable", degraded=True)
        d.data = {"mode": "local",
                  "answer": "The assistant is temporarily unavailable."}
        d.note("The assistant failed (%s)." % error.__class__.__name__)
        return d


def _context():
    inv = db.inventory_summary()
    st = db.stats()
    logs = db.recent_logs(8)
    lines = [f"Total items in stock: {inv['total']}", "Stock by product:"]
    for r in inv["rows"]:
        lines.append(f"  - {r['name']} ({r['category']}): {r['qty']}")
    lines.append(f"Distinct categories: {st['categories']}")
    lines.append(f"Total scans so far: {st['total_scans']}, anomalies flagged: {st['anomalies']}")
    lines.append("Recent activity:")
    for l in logs:
        lines.append(f"  - {l['action']} {l['name']} ({l['productno']})")
    return "\n".join(lines)


def _local_answer(question, context):
    """Deterministic fallback when Claude is unavailable."""
    q = (question or "").lower()
    inv = db.inventory_summary()
    st = db.stats()
    if any(k in q for k in ("how many", "total", "stock", "count")):
        parts = [f"There are {inv['total']} items in stock across {st['categories']} categories."]
        for r in inv["rows"][:6]:
            parts.append(f"{r['name']}: {r['qty']}")
        return " ".join(parts)
    if "anomal" in q or "problem" in q or "issue" in q:
        return f"{st['anomalies']} anomalies have been flagged out of {st['total_scans']} scans."
    if "categor" in q:
        cats = sorted({r["category"] for r in inv["rows"]})
        return "Categories in stock: " + (", ".join(cats) if cats else "none yet") + "."
    if "low" in q or "reorder" in q or "run out" in q:
        low = [r["name"] for r in inv["rows"] if r["qty"] <= 2]
        return ("Low stock: " + ", ".join(low)) if low else "No products are critically low right now."
    return ("Assistant (offline mode). Here is the current warehouse state:\n" + context)


def run(question):
    """Answer a question about current stock."""
    return AssistantAgent.instance.run({"question": question}).data


def _answer(question):
    context = _context()
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return {
            "agent": "Assistant Agent",
            "mode": "local",
            "answer": _local_answer(question, context),
        }

    try:
        import anthropic
    except Exception:
        return {
            "agent": "Assistant Agent",
            "mode": "local",
            "answer": _local_answer(question, context),
            "note": "anthropic SDK not installed; using offline responder.",
        }

    try:
        client = anthropic.Anthropic(api_key=api_key)
        system = (
            "You are the assistant for an AI-powered warehouse management system. "
            "Answer the user's question using ONLY the live inventory data provided. "
            "Be concise and practical. If the data does not contain the answer, say so."
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{
                "role": "user",
                "content": f"Live warehouse data:\n{context}\n\nQuestion: {question}",
            }],
        )
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        return {"agent": "Assistant Agent", "mode": "claude", "model": MODEL, "answer": answer}
    except Exception as e:
        return {
            "agent": "Assistant Agent",
            "mode": "local",
            "answer": _local_answer(question, context),
            "note": f"Claude call failed ({e.__class__.__name__}); used offline responder.",
        }
