"""
Model registry
==============
Runs the bake-off: trains every model on the same data, measures them the same
way, picks a winner, and keeps the winner loaded for the classifier agent to
use.

Selecting the winner
--------------------
Not by accuracy alone. With uneven class sizes, accuracy rewards a model for
being good at the big categories and quietly ignores a small one. The score used
here is:

    0.45 x cross-validated accuracy
  + 0.45 x macro F1          (every category counts equally)
  + 0.10 x consistency        (1 - std across folds)

Macro F1 carries as much weight as accuracy so that a model cannot win by
neglecting a small category, and the consistency term breaks ties in favour of
the model whose score does not swing between folds.

The chosen model is held in memory and its numbers are written to the database,
so the dashboard reports what is actually running rather than a figure typed
into a document once and never revisited.
"""

import threading

from ml import dataset, evaluate, metrics
from ml.models import ALL_MODELS, build_all

# Weights for the selection score. Exposed so the report can state them.
WEIGHT_ACCURACY = 0.45
WEIGHT_MACRO_F1 = 0.45
WEIGHT_CONSISTENCY = 0.10

CV_FOLDS = 5
SEED = 42

#: How much worse a newly trained model may be before it is refused. Below this
#: the difference is fold-to-fold noise; above it, something has genuinely got
#: worse and the model that is already working keeps running.
REGRESSION_TOLERANCE = 0.02

_lock = threading.Lock()
_state = {
    "active": None,        # the trained model instance actually answering
    "results": None,       # the full comparison from the most recent run
    "live_stats": None,    # the comparison entry for the model that is running
    "trained_at": None,
}


def selection_score(cv_accuracy, macro_f1, cv_std):
    """The single number models are ranked by."""
    consistency = max(0.0, 1.0 - cv_std)
    return round(
        WEIGHT_ACCURACY * cv_accuracy
        + WEIGHT_MACRO_F1 * macro_f1
        + WEIGHT_CONSISTENCY * consistency,
        4,
    )


def train_all(include_learned=True, folds=CV_FOLDS, seed=SEED, quick=True):
    """Train and evaluate every model. Returns the full comparison.

    ``quick`` (the default) skips leave-one-out. LOO trains one model per
    example — on this corpus that is roughly a minute against three seconds for
    k-fold, and it is the weaker measure of the two anyway: its training sets
    overlap almost completely, so its variance estimate is optimistic. K-fold is
    the headline figure; LOO is available on request because the original MVP
    quoted one and the comparison has to be measured the same way to be fair.
    """
    from core import dbcore

    data = dataset.full_dataset(include_learned)
    if len(data) < 10:
        return {"ok": False, "error": "Not enough training data to evaluate models."}

    X = [text for text, _ in data]
    y = [label for _, label in data]
    labels = sorted(set(y))
    stats = dataset.dataset_stats(include_learned)

    results = []
    for model_cls in ALL_MODELS:
        def factory(cls=model_cls):
            return cls()

        cv = evaluate.cross_validate(factory, X, y, k=folds, seed=seed)
        holdout, fitted = evaluate.holdout_evaluate(factory, X, y, seed=seed)

        macro_f1 = cv["pooled"]["macro"]["f1"]
        score = selection_score(cv["cv_accuracy"], macro_f1, cv["cv_std"])

        entry = {
            "key": model_cls.key,
            "name": model_cls.name,
            "family": model_cls.family,
            "description": model_cls.description,
            "hyperparameters": fitted.hyperparameters(),
            "cv_accuracy": cv["cv_accuracy"],
            "cv_std": cv["cv_std"],
            "cv_min": cv["cv_min"],
            "cv_max": cv["cv_max"],
            "fold_accuracies": cv["fold_accuracies"],
            "macro_f1": macro_f1,
            "macro_precision": cv["pooled"]["macro"]["precision"],
            "macro_recall": cv["pooled"]["macro"]["recall"],
            "weighted_f1": cv["pooled"]["weighted"]["f1"],
            "per_class": cv["pooled"]["per_class"],
            "confusion": cv["pooled"]["confusion"],
            "top_confusions": cv["pooled"]["top_confusions"],
            "holdout_accuracy": holdout["accuracy"],
            "holdout_errors": holdout["errors"],
            "train_ms": round(fitted.train_ms, 2),
            "avg_train_ms": cv["avg_train_ms"],
            "score": score,
        }

        if not quick:
            entry["loo_accuracy"] = evaluate.leave_one_out(factory, X, y)["accuracy"]

        # Extras only some models can offer.
        if hasattr(fitted, "convergence"):
            entry["convergence"] = fitted.convergence()
        if hasattr(fitted, "top_terms"):
            entry["top_terms"] = {
                label: fitted.top_terms(label, limit=6) for label in labels}

        results.append(entry)

    results.sort(key=lambda r: -r["score"])
    winner = results[0]

    # Retrain the winner on everything. Cross-validation exists to estimate how
    # a model will generalise; once that estimate is in hand, the model that
    # actually runs should have seen all the data available.
    final = None
    for cls in ALL_MODELS:
        if cls.key == winner["key"]:
            final = cls()
            final.fit(X, y)
            break

    comparison = {
        "ok": True,
        "trained_at": dbcore.now_iso(),
        "dataset": stats,
        "labels": labels,
        "folds": folds,
        "seed": seed,
        "selection": {
            "weights": {
                "cv_accuracy": WEIGHT_ACCURACY,
                "macro_f1": WEIGHT_MACRO_F1,
                "consistency": WEIGHT_CONSISTENCY,
            },
            "winner": winner["key"],
            "winner_name": winner["name"],
            "winner_score": winner["score"],
            "reason": _explain_choice(results),
        },
        "models": results,
        "baseline": _baseline_comparison(results, stats),
    }

    # Refuse a regression. Every document about this project says the system
    # will not promote a model that scores worse than the one already running,
    # and until now nothing enforced it -- the newly trained model was swapped
    # in before the comparison was even looked at.
    with _lock:
        previous = _state["results"]
        keep_previous = False
        was = None
        if previous and previous.get("models") and _state["active"] is not None:
            was = previous["models"][0]["cv_accuracy"]
            keep_previous = winner["cv_accuracy"] < was - REGRESSION_TOLERANCE

        comparison["promoted"] = not keep_previous
        if keep_previous:
            comparison["kept_model"] = previous["models"][0]["name"]
            comparison["regression"] = round(was - winner["cv_accuracy"], 4)
            # The evaluation is still recorded -- a refusal is a result worth
            # keeping -- but the model that answers requests does not change.
            # live_stats is deliberately NOT updated: the figures on the
            # dashboard must describe the model that is answering, not the one
            # that was just rejected.
            _state["results"] = comparison
            _state["trained_at"] = comparison["trained_at"]
        else:
            _state["active"] = final
            _state["live_stats"] = winner
            _state["results"] = comparison
            _state["trained_at"] = comparison["trained_at"]

    return comparison


def _explain_choice(results):
    """A sentence a reader can check against the table."""
    winner = results[0]
    if len(results) == 1:
        return "%s was the only model evaluated." % winner["name"]
    runner_up = results[1]
    gap = round(winner["score"] - runner_up["score"], 4)
    parts = [
        "%s scored %.4f against %.4f for %s."
        % (winner["name"], winner["score"], runner_up["score"], runner_up["name"])
    ]
    if winner["cv_accuracy"] >= runner_up["cv_accuracy"]:
        parts.append("It is more accurate under %d-fold cross-validation "
                     "(%.1f%% against %.1f%%)."
                     % (CV_FOLDS, winner["cv_accuracy"] * 100,
                        runner_up["cv_accuracy"] * 100))
    else:
        parts.append("It is slightly less accurate than %s (%.1f%% against "
                     "%.1f%%) but more even across the categories, and macro F1 "
                     "counts every category equally."
                     % (runner_up["name"], winner["cv_accuracy"] * 100,
                        runner_up["cv_accuracy"] * 100))
    if gap < 0.02:
        parts.append("The margin is narrow, so this is a preference rather than "
                     "a decisive result.")
    return " ".join(parts)


def _baseline_comparison(results, stats):
    """This system's classifier against the original MVP's.

    The old figure is not guessed: the first release trained Naive Bayes on 20
    samples and measured 70% leave-one-out. That is the number this comparison
    improves on, and it is stated here so the claim can be checked.
    """
    winner = results[0]
    old_accuracy = 0.70
    old_samples = 20
    new_accuracy = winner["cv_accuracy"]
    return {
        "previous": {
            "model": "Multinomial Naive Bayes",
            "training_samples": old_samples,
            "accuracy": old_accuracy,
            "method": "leave-one-out cross-validation",
            "note": "The classifier shipped with the first MVP.",
        },
        "current": {
            "model": winner["name"],
            "training_samples": stats["total"],
            "classes": stats["classes"],
            "accuracy": new_accuracy,
            "macro_f1": winner["macro_f1"],
            "method": "%d-fold stratified cross-validation" % CV_FOLDS,
        },
        "absolute_gain": round(new_accuracy - old_accuracy, 4),
        "relative_gain": round((new_accuracy - old_accuracy) / old_accuracy, 4)
                         if old_accuracy else 0.0,
        "error_reduction": round(
            ((1 - old_accuracy) - (1 - new_accuracy)) / (1 - old_accuracy), 4)
            if old_accuracy < 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# The live model
# ---------------------------------------------------------------------------
def active_model():
    """The model currently answering classification requests.

    Trains on first use so a fresh install has a working classifier without
    anyone having to press a button.
    """
    with _lock:
        if _state["active"] is not None:
            return _state["active"]
    train_all(quick=True)
    with _lock:
        return _state["active"]


def last_results():
    with _lock:
        return _state["results"]


def invalidate():
    """Drop the trained model so the next request retrains it.

    Called when the user assigns a category, since that is a new labelled
    example and the model should pick it up.
    """
    with _lock:
        _state["active"] = None
        _state["live_stats"] = None


def summary():
    """A compact view for the dashboard header.

    Reports the model that is actually answering requests. After a refused
    promotion those are not the same thing, and quoting the rejected model's
    accuracy next to the running model's name would be simply wrong.
    """
    results = last_results()
    if not results:
        return {"trained": False}
    with _lock:
        live = _state["live_stats"]
    winner = live or results["models"][0]
    return {
        "trained": True,
        "trained_at": results["trained_at"],
        "model": winner["name"],
        "model_key": winner["key"],
        "accuracy": winner["cv_accuracy"],
        "macro_f1": winner["macro_f1"],
        "samples": results["dataset"]["total"],
        "classes": results["dataset"]["classes"],
        "improvement": results["baseline"]["absolute_gain"],
        "promoted": results.get("promoted", True),
        "evaluated_model": results["models"][0]["name"],
    }
