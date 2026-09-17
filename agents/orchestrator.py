"""
Orchestrator
============
Coordinates the agents. It does not decide anything itself — it decides *who
decides*, in what order, and what to do when one of them cannot answer.

Pipeline per scan
-----------------
    Scanner -> [Recovery] -> Resolution -> Classifier -> Inventory
            -> Anomaly -> Forecast -> commit

Recovery runs only when it is needed: when the scanner cannot parse the input,
or when a code parses cleanly but matches nothing in stock. That is the
difference between a system that stops at a bad read and one that keeps working
through it.

Every agent's decision is recorded in the trace and stored with the log entry,
so any figure in this warehouse can be traced back to the agent that produced it
and the evidence it used.
"""

import threading
import time

import db
from agents import scanner_agent, inventory_agent, anomaly_agent, forecast_agent
from agents.base import registry

# ---------------------------------------------------------------------------
# Duplicate suppression
# ---------------------------------------------------------------------------
# A camera is a sampling device, not a button. html5-qrcode re-decodes roughly
# twelve times a second, and every successful decode used to become a unit of
# stock -- so one box held under the lens for a second became a dozen. The
# browser suppresses this at source; this is the backstop, because a page
# reload, a second tab, or a replayed request all start with an empty browser.
#
# monotonic(), not wall-clock: a clock correction mid-shift must not widen or
# collapse the window.
_recent = {}
_recent_lock = threading.Lock()
_last_prune = {"t": 0.0}

#: Suppressed reads are counted rather than logged. They are not events that
#: happened to the stock, so an append-only stock trail is the wrong place for
#: them -- but a silent control is an untrustworthy one, so the tally is
#: reported on the Agents screen.
_suppressed = {"n": 0}


def duplicates_suppressed():
    return _suppressed["n"]


def _prune(now, window):
    """Drop entries older than the window. Time-based, so a busy warehouse does
    not pay an O(n) sweep on every single scan."""
    if now - _last_prune["t"] < max(window, 5.0):
        return
    _last_prune["t"] = now
    cutoff = now - max(window, 5.0) * 2
    for key in [k for k, t in _recent.items() if t < cutoff]:
        _recent.pop(key, None)


def _duplicate_key(actor, productno, mode, batchno):
    # Keyed per person: two pickers working the same SKU at adjacent stations
    # are two real units, not a double read.
    return ((actor or {}).get("id"), productno, mode, batchno)


def _is_duplicate(key, window):
    if window <= 0:
        return False
    now = time.monotonic()
    with _recent_lock:
        _prune(now, window)
        seen = _recent.get(key)
        return seen is not None and (now - seen) < window


def _remember(key):
    """Stamp a code as counted. Called only *after* the stock write succeeded,
    so a scan that failed can be retried immediately instead of being locked
    out for the length of the window."""
    with _recent_lock:
        _recent[key] = time.monotonic()


def reset_duplicate_state():
    """Clear the window. For tests, so one case cannot bleed into the next."""
    with _recent_lock:
        _recent.clear()
        _suppressed["n"] = 0


def process_scan(code, mode, fmt="unknown", actor=None, allow_recovery=True):
    """Run one scan through the whole pipeline.

    ``actor`` is the signed-in staff member, recorded against the log entry.
    ``allow_recovery`` can be turned off when the caller has already applied a
    repair and does not want a second one layered on top.
    """
    trace = []
    recovery_info = None

    # 1. Scanner Agent -- perception ------------------------------------
    parsed = scanner_agent.run(code, fmt)
    parsed["code"] = code
    trace.append(parsed)

    # 1a. Recovery Agent -- the backup scanner ---------------------------
    # A scan the scanner could not parse is not necessarily a lost scan.
    if not parsed.get("ok"):
        if allow_recovery:
            recovered, recovery_info = _attempt_recovery(code, parsed.get("reason", ""), trace)
            if recovered:
                return _rerun_with(recovered, mode, fmt, actor, trace, recovery_info)
        db.add_log(code, None, None, "REJECT", None, True, trace, actor=actor)
        return {
            "ok": False, "final": "REJECT", "reason": parsed.get("reason"),
            "code": code, "trace": trace, "recovery": recovery_info,
            # The scan never became a product at all, so offering repairs is
            # the right thing to do here.
            "unresolved": True,
        }

    # 1b. Resolution -- match a bare code to stock we already hold --------
    matched = _resolve(parsed)

    # 1c. Recovery for a well-formed code that matches nothing ------------
    # This is the check-digit and clipped-read case: the string is valid, it
    # simply is not any product we have. Worth one repair attempt before the
    # units land on a new, nameless record.
    if (allow_recovery and not matched
            and parsed["name"] in (None, "", db.UNKNOWN_NAME)):
        recovered, recovery_info = _attempt_recovery(
            code, "The code parsed but matches no product in stock.", trace)
        if recovered:
            return _rerun_with(recovered, mode, fmt, actor, trace, recovery_info)

    # 1d. Duplicate suppression ------------------------------------------
    # Now that the code has been resolved to the product it actually is, a
    # repeat read can be recognised even when the QR and the printed barcode
    # spell it differently. Deliberate input is exempt: repeat manual entry is
    # how someone legitimately counts five identical boxes in.
    deliberate = fmt in anomaly_agent.DELIBERATE_FORMATS
    window = 0.0 if deliberate else anomaly_agent.double_read_window()
    dup_key = _duplicate_key(actor, parsed["productno"], mode, parsed.get("batchno") or "")

    if _is_duplicate(dup_key, window):
        with _recent_lock:
            _suppressed["n"] += 1
        trace.append({
            "agent": "Anomaly Agent",
            "verdict": "REJECT",
            "confidence": 1.0,
            "method": "duplicate read suppression",
            "rationale": [
                "%s was already counted less than %.1fs ago." % (parsed["name"], window),
                "The camera reads the same label many times a second; only the "
                "first read of a presentation becomes stock.",
                "Present the label again after %.1fs to count another unit." % window,
            ],
        })
        return {
            "ok": True,
            "final": "DUPLICATE",
            "duplicate": True,
            "name": parsed["name"],
            "productno": parsed["productno"],
            "batchno": parsed.get("batchno", ""),
            "code": code,
            "qty": db.product_total(parsed["productno"]),
            "window": window,
            "reason": ("Already counted %.1fs ago — the same label read twice. "
                       "Nothing was added." % window),
            "anomaly": False,
            "trace": trace,
            "actor": (actor or {}).get("username", ""),
        }

    # 2. Classifier Agent -- category suggestion --------------------------
    catalog_hint = db.catalog_lookup(parsed["name"])
    known_in_catalog = catalog_hint is not None and catalog_hint != db.UNCATEGORISED
    classify = _classify(parsed["name"], catalog_hint)
    trace.append(classify)
    category = classify["category"]

    # 3. Inventory Agent -- decision and action ---------------------------
    inv = inventory_agent.run(parsed, mode, category)
    trace.append(inv)

    # 4. Anomaly Agent -- statistical check -------------------------------
    parsed["actor"] = actor          # so a double-read is judged per person
    anomaly = anomaly_agent.run(parsed, inv, known_in_catalog)
    trace.append(anomaly)

    # 5. Forecast Agent -- stock-out estimate -----------------------------
    forecast = forecast_agent.run(parsed["name"])
    trace.append(forecast)

    # 6. Commit -----------------------------------------------------------
    action = inv["action"]
    log_id = db.add_log(code, parsed["name"], parsed["productno"], action, category,
                        anomaly["flagged"], trace, inv.get("batchno", ""), actor=actor)

    # Stamp only now, once the unit is safely recorded. Stamping earlier would
    # mean a scan that failed on the way to the database was locked out of a
    # retry — turning a visible error into silent stock loss.
    if not deliberate:
        _remember(dup_key)

    return {
        "ok": inv["decision"] == "ACCEPT",
        "final": action,
        "log_id": log_id,
        "name": parsed["name"],
        "productno": parsed["productno"],
        "batchno": inv.get("batchno", ""),
        "code": code,
        "category": category,
        "qty": inv.get("qty"),
        "needs_category": category == db.UNCATEGORISED and bool(parsed["name"]),
        # True only when the code matched no product. A rejection because a
        # product is already at zero is NOT an unresolved code, and offering
        # to "repair" it sends the operator further from the real item.
        "unresolved": not matched and parsed["name"] in (None, "", db.UNKNOWN_NAME),
        "suggestion": classify.get("suggestion"),
        "reason": inv["reason"],
        "anomaly": anomaly["flagged"],
        "anomaly_reasons": anomaly.get("reasons", []),
        "forecast": {
            "days_to_stockout": forecast.get("days_to_stockout"),
            "below_reorder": forecast.get("below_reorder", False),
        },
        "recovery": recovery_info,
        "actor": (actor or {}).get("username", ""),
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------
def _resolve(parsed):
    """Match a bare product number to a product already in stock.

    A plain barcode carries no name and no batch. Without this the scan enters
    stock as a second, nameless row beside the product it actually is.
    Returns True when something was matched.
    """
    if parsed["name"] not in (None, "", db.UNKNOWN_NAME):
        return True

    canonical, how = db.resolve_productno(parsed["productno"])
    if canonical and canonical != parsed["productno"]:
        parsed["notes"].append(
            "Scanned code %s matches stored product no. %s (%s)."
            % (parsed["productno"], canonical, how))
        parsed["scanned_code"] = parsed["productno"]
        parsed["productno"] = canonical

    known = db.lookup_product(canonical or parsed["productno"])
    if not known:
        return False

    parsed["name"] = known["name"]
    parsed["confidence"] = max(parsed.get("confidence", 0), 0.9)
    parsed["notes"].append("Matched product no. %s to known product '%s'."
                           % (parsed["productno"], known["name"]))
    if not parsed["batchno"] and known["batchno"]:
        parsed["batchno"] = known["batchno"]
        parsed["notes"].append("Using its existing batch %s." % known["batchno"])
    parsed["matched"] = True
    return True


def _classify(name, catalog_hint):
    """Ask the classifier agent, in the trace format the pipeline uses."""
    from agents import classifier_agent
    return classifier_agent.run(name, catalog_hint, db.category_names())


def _attempt_recovery(code, reason, trace):
    """Ask the Recovery Agent whether this scan can be salvaged.

    Returns ``(repaired_code_or_None, info)``. A repair is only applied on its
    own when the agent is confident *and* the result matches real stock;
    anything less is returned for a person to confirm.
    """
    agent = registry.get("Recovery Agent")
    if agent is None:
        return None, None

    decision = agent.run({"code": code, "reason": reason})
    trace.append(decision.to_dict())

    info = {
        "attempted": True,
        "repaired": decision.data.get("repaired"),
        "strategy": decision.data.get("strategy"),
        "confidence": decision.confidence,
        "auto_applied": bool(decision.data.get("auto_apply")),
        "candidates": decision.data.get("candidates", []),
        "advice": decision.data.get("advice"),
        "fields": decision.data.get("fields", {}),
    }
    if decision.data.get("auto_apply") and decision.data.get("repaired"):
        return decision.data["repaired"], info
    return None, info


def _rerun_with(repaired_code, mode, fmt, actor, trace, recovery_info):
    """Re-run the pipeline on a repaired code, keeping the original trace.

    Recovery is disabled on the second pass: one repair is a fix, a chain of
    them is guesswork.
    """
    result = process_scan(repaired_code, mode, fmt, actor=actor, allow_recovery=False)
    # Put the original scanner and recovery steps in front, so the trace shows
    # what actually happened rather than only the successful retry.
    result["trace"] = trace + result.get("trace", [])
    result["recovery"] = recovery_info
    result["recovered_from"] = recovery_info.get("repaired") and True or False
    return result


# ---------------------------------------------------------------------------
# Standalone recovery, for the UI's "help me with this failed scan" path
# ---------------------------------------------------------------------------
def recover(code, reason=""):
    """Run only the Recovery Agent and return its candidates.

    Used by the scanner screen when a read fails: it offers the operator the
    repairs it found instead of a dead end.
    """
    agent = registry.get("Recovery Agent")
    if agent is None:
        return {"ok": False, "error": "The recovery agent is not available."}
    decision = agent.run({"code": code, "reason": reason})
    return {
        "ok": decision.verdict != "REJECT",
        "repaired": decision.data.get("repaired"),
        "strategy": decision.data.get("strategy"),
        "confidence": decision.confidence,
        "auto_apply": bool(decision.data.get("auto_apply")),
        "candidates": decision.data.get("candidates", []),
        "advice": decision.data.get("advice"),
        "rationale": decision.rationale,
        "trace": [decision.to_dict()],
    }
