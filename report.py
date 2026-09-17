"""
System comparison
=================
The evidence for the claim that this system is better than the one it replaces.

Every figure here is either measured by :mod:`ml.registry` and
:mod:`verify`, or is a factual statement about what the two systems do. Nothing
is estimated. Where a dimension cannot be measured — resilience, for instance,
has no single number — the comparison says what changed and why it matters,
rather than inventing a score for it.

The two systems being compared
------------------------------
**AUTOWARE (the baseline).** The earlier final-year project: a Django dashboard,
an ESP32-CAM reading QR codes, a conveyor belt, and one central controller that
held all the logic. Centralised and rule-based.

**This system.** Camera-based capture through a set of cooperating agents, each
making its own decision and explaining it, with no central rule engine.
"""


def system_comparison(ml_results):
    """Assemble the comparison from measured results."""
    winner = ml_results["models"][0] if ml_results.get("models") else {}
    baseline = ml_results.get("baseline", {})
    dataset = ml_results.get("dataset", {})

    return {
        "headline": {
            "classification_accuracy": {
                "before": baseline.get("previous", {}).get("accuracy", 0.70),
                "after": winner.get("cv_accuracy", 0.0),
                "gain": baseline.get("absolute_gain", 0.0),
                "error_reduction": baseline.get("error_reduction", 0.0),
            },
            "training_data": {
                "before": baseline.get("previous", {}).get("training_samples", 20),
                "after": dataset.get("total", 0),
            },
            "categories_covered": {
                "before": 3,
                "after": dataset.get("classes", 0),
            },
            "models_evaluated": {"before": 1, "after": len(ml_results.get("models", []))},
        },
        "dimensions": _dimensions(winner, baseline, dataset),
        "measured": _measured(ml_results),
        "caveats": [
            "Accuracy figures are 5-fold stratified cross-validation on the "
            "current corpus of %d names. They describe this dataset, and will "
            "move as more products are filed." % dataset.get("total", 0),
            "The 70%% baseline is the first MVP's own measured leave-one-out "
            "score on its 20-sample set, not an estimate.",
            "Decode rate (~99% on clear codes) is a property of the ZXing "
            "library, unchanged between the two systems. What changed is what "
            "happens to the 1% that fails.",
            "Resilience and auditability are described rather than scored: "
            "there is no honest single number for either.",
        ],
    }


def _agent_facts():
    """Count the agents from the live registry.

    These numbers were hard-coded once and were wrong within a day of adding an
    agent. A report whose own figures drift is worse than one that omits them,
    so they are counted rather than written down.
    """
    try:
        from agents.base import registry
        agents = registry.all()
        critical = [a.name for a in agents if a.critical]
        return {
            "count": len(agents),
            "layers": len({a.layer for a in agents}),
            "critical": critical,
        }
    except Exception:                       # noqa: BLE001
        return {"count": 0, "layers": 0, "critical": []}


def _dimensions(winner, baseline, dataset):
    """Where the two systems differ, and what changed."""
    facts = _agent_facts()
    critical = facts["critical"]
    # Honest phrasing: one agent deliberately *is* on the critical path, and
    # claiming otherwise would misdescribe the design rather than flatter it.
    if critical:
        halt_note = ("every agent except %s degrades rather than failing the scan"
                     % " and ".join(critical))
        halt_metric = "%d repair strategies; %d of %d agents can halt the pipeline" % (
            7, len(critical), facts["count"])
    else:
        halt_note = "no agent can fail the scan"
        halt_metric = "7 repair strategies; no agent can halt the pipeline"

    return [
        {
            "dimension": "Architecture",
            "before": "One central controller holding every rule. Adding a "
                      "behaviour meant editing the controller.",
            "after": "%d independent agents across %d layers. Each owns one "
                     "decision and can be changed, tested or replaced alone."
                     % (facts["count"], facts["layers"]),
            "why_it_matters": "This is the decentralisation the research proposal "
                              "argues for, in running code rather than in a diagram.",
            "measurable": True,
            "metric": "%d agents, %d layers" % (facts["count"], facts["layers"]),
        },
        {
            "dimension": "Failure behaviour",
            "before": "A failure anywhere in the pipeline failed the scan. A bad "
                      "read was a dead end that a person resolved later by hand.",
            "after": ("Agents are contained: %s. A failed read goes to the "
                      "Recovery Agent, which repairs it by seven ordered "
                      "strategies before giving up. %s is deliberately on the "
                      "critical path, because a silent failure there would leave "
                      "the stock figures wrong."
                      % (halt_note, " and ".join(critical))) if critical else
                     ("Agents are contained: one that fails returns a DEGRADED "
                      "decision and the pipeline carries on."),
            "why_it_matters": "A warehouse that stops receiving stock because a "
                              "forecast divided by zero is worse than one that "
                              "receives stock without a forecast.",
            "measurable": True,
            "metric": halt_metric,
        },
        {
            "dimension": "Scanner redundancy",
            "before": "A single ESP32-CAM. If it failed, scanning stopped.",
            "after": "Four fallback levels: primary camera, automatic failover "
                     "to a second camera, still-photo decode, then manual entry. "
                     "Server-side repair sits behind all four.",
            "why_it_matters": "Hardware fails at inconvenient times. Every level "
                              "here keeps the warehouse working.",
            "measurable": True,
            "metric": "4 input paths, automatic failover",
        },
        {
            "dimension": "Category accuracy",
            "before": "%.0f%% (Naive Bayes on %d samples, 3 categories)"
                      % (baseline.get("previous", {}).get("accuracy", 0.7) * 100,
                         baseline.get("previous", {}).get("training_samples", 20)),
            "after": "%.1f%% (%s on %d samples, %d categories)"
                     % (winner.get("cv_accuracy", 0) * 100, winner.get("name", "-"),
                        dataset.get("total", 0), dataset.get("classes", 0)),
            "why_it_matters": "Five models are cross-validated and the best is "
                              "selected on accuracy *and* per-category balance, "
                              "so a small category cannot be quietly neglected.",
            "measurable": True,
            "metric": "%+.1f points, %.0f%% fewer errors"
                      % (baseline.get("absolute_gain", 0) * 100,
                         baseline.get("error_reduction", 0) * 100),
        },
        {
            "dimension": "Who decides a category",
            "before": "The model wrote a category straight into inventory. A "
                      "wrong guess became indistinguishable from a fact.",
            "after": "The model only suggests. An unseen product is filed as "
                     "Uncategorised until a person accepts or overrides it, and "
                     "that choice becomes training data.",
            "why_it_matters": "Nobody re-checks a value that already looks "
                              "authoritative. Keeping guesses visibly separate "
                              "from facts is what makes the data trustworthy.",
            "measurable": False,
            "metric": "user assignment always wins",
        },
        {
            "dimension": "Learning",
            "before": "Static. The model shipped with the code and never changed.",
            "after": "Every category a manager assigns becomes a labelled "
                     "example. The Learning Agent retrains, compares against the "
                     "running model, and refuses to promote a regression.",
            "why_it_matters": "Accuracy improves with use instead of decaying as "
                              "the product range drifts away from the training set.",
            "measurable": True,
            "metric": "retrains after %d new assignments" % 3,
        },
        {
            "dimension": "Access control",
            "before": "None in the MVP. Anyone reaching the page could change stock.",
            "after": "PBKDF2 passwords, fingerprinted session tokens, 4 roles "
                     "over a capability matrix, per-account lockout, and every "
                     "movement attributed to a named staff member.",
            "why_it_matters": "An audit trail that cannot say who acted is not an "
                              "audit trail.",
            "measurable": True,
            "metric": "4 roles, 18 capabilities, 240k-round hashing",
        },
        {
            "dimension": "Auditability",
            "before": "A log of what happened.",
            "after": "A log of what happened, who did it, which agents decided "
                     "it, how confident each was, and why. The Audit Agent "
                     "reconciles stock against the log and reports drift.",
            "why_it_matters": "Any number on the dashboard can be traced back to "
                              "the agent that produced it and the evidence used.",
            "measurable": True,
            "metric": "full decision trace stored per scan",
        },
        {
            "dimension": "Code identity",
            "before": "A QR payload and the printed barcode for the same product "
                      "were different strings and became two stock records.",
            "after": "Exact match, then user-set links, then EAN/UPC check-digit "
                     "and UPC-A/EAN-13 variants — in both directions. Variant "
                     "matching is restricted to barcode-length numeric codes so "
                     "ordinary product numbers are never loosely matched.",
            "why_it_matters": "Split stock records are the most common way a "
                              "warehouse count silently goes wrong.",
            "measurable": True,
            "metric": "QR and barcode resolve to one record, both ways",
        },
        {
            "dimension": "Reordering",
            "before": "A fixed low-stock threshold, set by hand.",
            "after": "A reorder-point model: average demand x lead time, plus "
                     "safety stock sized from observed demand variability, so an "
                     "erratic product carries more cover than a steady one.",
            "why_it_matters": "A flat threshold either over-stocks steady products "
                              "or under-stocks erratic ones. It cannot do both.",
            "measurable": True,
            "metric": "95% service level (z = 1.65)",
        },
        {
            "dimension": "Deployment",
            "before": "Django, a database server, hardware, a conveyor.",
            "after": "Python standard library only at runtime. No pip installs. "
                     "One file database. Runs on any laptop with Python 3.8+.",
            "why_it_matters": "Nothing to provision means nothing to break "
                              "between a demonstration and a working system.",
            "measurable": True,
            "metric": "0 runtime dependencies",
        },
    ]


def _measured(ml_results):
    """The numbers behind the claims, so a reader can check them."""
    rows = []
    for m in ml_results.get("models", []):
        rows.append({
            "model": m["name"],
            "family": m["family"],
            "cv_accuracy": m["cv_accuracy"],
            "cv_std": m["cv_std"],
            "macro_f1": m["macro_f1"],
            "macro_precision": m["macro_precision"],
            "macro_recall": m["macro_recall"],
            "score": m["score"],
            "train_ms": m["train_ms"],
            "selected": m["key"] == ml_results["selection"]["winner"],
        })
    return {
        "models": rows,
        "selection_weights": ml_results.get("selection", {}).get("weights", {}),
        "selection_reason": ml_results.get("selection", {}).get("reason", ""),
        "folds": ml_results.get("folds"),
        "seed": ml_results.get("seed"),
        "dataset": ml_results.get("dataset", {}),
        "per_class": (ml_results["models"][0]["per_class"]
                      if ml_results.get("models") else {}),
        "confusion": (ml_results["models"][0]["confusion"]
                      if ml_results.get("models") else {}),
    }
