"""
Anomaly Agent  (statistical detection)
======================================
Watches the stream of scans and flags anything unusual. Combines simple rules
with a running statistical model (online mean / standard deviation of the time
BETWEEN scans) to catch double-reads and abnormal bursts — the kind of
lightweight, explainable ML that runs comfortably on-device.

Flags raised:
  * double-read   : same code scanned again within a very short window
  * rate spike    : gap between scans is a statistical outlier (z-score based)
  * unknown item  : product name not in the catalogue (barcode-only / new SKU)
  * rejected move : the inventory agent refused the action
"""

import math
import time

from agents.base import Agent, Decision, ACCEPT, FLAG, register


class _RunningStats:
    """Welford's online algorithm for mean + variance of inter-scan gaps."""

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def update(self, x):
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

    def std(self):
        if self.n < 2:
            return 0.0
        return math.sqrt(self.m2 / (self.n - 1))


# Module-level state (single-process MVP).
import threading

_last_time = {"t": None}
# Keyed by (person, product, batch), not by code alone. One global "last code"
# slot meant two pickers on the same SKU flagged each other, one picker moving
# between batches flagged themselves, and alternating A,B,A,B never flagged at
# all -- and every false flag inflated the dashboard's anomaly count, which the
# Audit Agent then reported as a scanner problem the system had invented.
_recent_reads = {}
_reads_lock = threading.Lock()
_gaps = _RunningStats()

#: Fallback window, used only if the setting cannot be read. The live value is
#: the ``double_read_window`` setting, so a manager can widen or narrow it.
DOUBLE_READ_WINDOW = 1.5  # seconds

#: Input formats that represent a *deliberate* human action rather than a
#: camera sampling the same label many times a second. Repeat entry through any
#: of these is how stock is legitimately built up, so it is never suppressed and
#: never flagged.
DELIBERATE_FORMATS = ("manual", "sample", "photo", "recovered")


def double_read_window():
    """The live double-read window, in seconds."""
    try:
        from store import settings
        value = float(settings.get("double_read_window", DOUBLE_READ_WINDOW))
        return value if value > 0 else 0.0
    except Exception:                        # noqa: BLE001 - never fail a scan
        return DOUBLE_READ_WINDOW


@register
class AnomalyAgent(Agent):
    name = "Anomaly Agent"
    role = "Flags double-reads, rate spikes, unknown SKUs and rejected moves."
    method = "rules + Welford online mean/sigma with z-score outlier test"
    layer = "operations"

    def decide(self, context):
        result = _detect(context["item"], context["inventory"],
                         context["known_in_catalog"])
        d = Decision(self.name, FLAG if result["flagged"] else ACCEPT,
                     result["score"] if result["flagged"] else 1.0 - result["score"],
                     result["reasons"], method=self.method)
        d.data = {k: v for k, v in result.items() if k not in ("agent", "reasons")}
        return d

    def fallback(self, context, error):
        """Anomaly detection is advisory; a failure must not block a scan."""
        d = Decision(self.name, ACCEPT, 0.0, method="unavailable", degraded=True)
        d.data = {"flagged": False, "score": 0.0}
        d.note("Anomaly detection is unavailable (%s)." % error.__class__.__name__)
        d.note("The movement was allowed; it simply was not checked.")
        return d


def run(item, inv_result, known_in_catalog):
    """Check one movement, in the trace format the pipeline uses."""
    decision = AnomalyAgent.instance.run({
        "item": item, "inventory": inv_result, "known_in_catalog": known_in_catalog})
    out = decision.to_dict()
    out["agent"] = AnomalyAgent.name
    out["reasons"] = out.get("rationale", [])
    return out


def _detect(item, inv_result, known_in_catalog):
    reasons = []
    score = 0.0
    now = time.time()
    code = item.get("productno")

    # --- double-read detection -------------------------------------------
    # Only a camera can physically re-read the same label in consecutive frames.
    # Repeat manual entries and sample-chip clicks are deliberate: under the
    # quantity model they are the normal way to add several units, so they must
    # never be flagged.
    from_camera = item.get("format") not in DELIBERATE_FORMATS
    window = double_read_window()
    key = ((item.get("actor") or {}).get("id"), code, item.get("batchno") or "")
    if from_camera and window > 0:
        with _reads_lock:
            seen = _recent_reads.get(key)
            _recent_reads[key] = now
            # Bound the map. A warehouse scans all day; this must not grow
            # without limit.
            if len(_recent_reads) > 512:
                cutoff = now - max(window, 5.0) * 4
                for k in [k for k, t in _recent_reads.items() if t < cutoff]:
                    _recent_reads.pop(k, None)
        if seen is not None and (now - seen) < window:
            reasons.append(
                "Same item scanned twice within %.1fs (likely double-read)." % window)
            score += 0.5

    # --- statistical rate-spike detection --------------------------------
    if _last_time["t"] is not None:
        gap = now - _last_time["t"]
        std = _gaps.std()
        # Deliberate clicking is not a rate spike — only judge camera input.
        if from_camera and _gaps.n >= 5 and std > 0:
            z = (gap - _gaps.mean) / std
            if z < -2.5:  # scans arriving far faster than normal
                reasons.append("Scan rate spike (z=%.1f) — unusually fast input." % z)
                score += 0.4
        _gaps.update(gap)
    _last_time["t"] = now

    # --- unknown item ----------------------------------------------------
    if not known_in_catalog and item.get("name") not in (None, "Unknown Item"):
        reasons.append("Product has no category assigned yet — new or mislabelled SKU.")
        score += 0.2
    if item.get("name") == "Unknown Item":
        reasons.append("Unidentified item (barcode only, no product name).")
        score += 0.2

    # --- rejected inventory move ----------------------------------------
    if inv_result.get("decision") == "REJECT":
        reasons.append("Inventory move was rejected: " + inv_result.get("reason", ""))
        score += 0.3

    flagged = score >= 0.5
    return {
        "agent": "Anomaly Agent",
        "flagged": flagged,
        "score": round(min(score, 1.0), 2),
        "reasons": reasons or ["No anomalies detected."],
    }
