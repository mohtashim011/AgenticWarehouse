"""
Perception / Scanner Agent
==========================
Turns a raw decoded string (from a QR code *or* a 1-D barcode) into a clean,
structured item record. This is the "eyes" of the system — the AI vision step
happens in the browser (camera -> QR/barcode decode); this agent validates and
normalises the result.

Two input shapes are supported:
  1. QR payload  ->  "name,batchno,productno"   (the AUTOWARE format)
  2. Raw barcode ->  "8901234567890"            (EAN/UPC/Code128 -> treated as productno)
"""

import re

from agents.base import Agent, Decision, ACCEPT, REJECT, register


def _clean(s):
    return (s or "").strip()


@register
class ScannerAgent(Agent):
    name = "Scanner Agent"
    role = "Parses and validates whatever the camera decoded."
    method = "payload grammar + character validation"
    layer = "perception"

    def decide(self, context):
        parsed = _parse(context.get("code", ""), context.get("format", "unknown"))
        d = Decision(self.name, ACCEPT if parsed["ok"] else REJECT,
                     parsed.get("confidence", 0.0), parsed.get("notes", []),
                     method=self.method)
        d.data = {k: v for k, v in parsed.items() if k not in ("notes", "agent")}
        return d

    def fallback(self, context, error):
        """A parser failure must be reported, never guessed around.

        Recovery happens in the Recovery Agent, which is built for it. Inventing
        a product number here would put stock on the wrong record.
        """
        d = Decision(self.name, REJECT, 0.0, method="unavailable", degraded=True)
        d.data = {"ok": False, "reason": "The scan could not be parsed.",
                  "name": None, "batchno": None, "productno": None}
        d.note("The scanner agent failed (%s)." % error.__class__.__name__)
        d.note("The scan was rejected rather than guessed at.")
        return d


def run(code, fmt="unknown"):
    """Parse a scanned code. Returns a structured message from the Scanner Agent."""
    decision = ScannerAgent.instance.run({"code": code, "format": fmt})
    out = decision.to_dict()
    out["agent"] = ScannerAgent.name
    out["notes"] = out.get("rationale", [])
    return out


def _parse(code, fmt="unknown"):
    code = _clean(code)
    confidence = 1.0
    notes = []

    if not code:
        return {
            "agent": "Scanner Agent",
            "ok": False,
            "reason": "Empty scan.",
            "name": None, "batchno": None, "productno": None,
            "confidence": 0.0, "notes": ["No data decoded from the camera."],
        }

    if "," in code:
        # QR payload: name,batchno,productno
        parts = [p.strip() for p in code.split(",")]
        if len(parts) >= 3:
            name, batchno, productno = parts[0], parts[1], parts[2]
            notes.append("Parsed structured QR payload (name, batch, product no).")
        elif len(parts) == 2:
            name, batchno, productno = parts[0], "", parts[1]
            confidence = 0.8
            notes.append("QR had 2 fields; assumed name + product no.")
        else:
            name, batchno, productno = parts[0], "", parts[0]
            confidence = 0.5
            notes.append("QR had 1 field; used it as product no.")
    else:
        # Raw 1-D barcode: the whole value is the product number.
        productno = code
        batchno = ""
        name = "Unknown Item"
        confidence = 0.7
        notes.append("Plain barcode detected; product no. taken from barcode value.")

    if not re.fullmatch(r"[A-Za-z0-9_\-./]+", productno or ""):
        confidence = min(confidence, 0.5)
        notes.append("Product no. contains unusual characters.")

    return {
        "agent": "Scanner Agent",
        "ok": True,
        "name": _clean(name) or "Unknown Item",
        "batchno": _clean(batchno),
        "productno": _clean(productno),
        "format": fmt,
        "confidence": round(confidence, 2),
        "notes": notes,
    }
