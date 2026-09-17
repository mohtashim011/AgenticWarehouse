"""
Learning Agent
==============
Owns the models: decides when they are stale, retrains them, compares them, and
picks which one runs.

This is the agent that makes the system improve with use rather than staying at
whatever accuracy it shipped with. Every time a manager files a product under a
category they have produced a labelled example from the person who actually
knows the answer. This agent notices those accumulating, decides when there are
enough to be worth acting on, and retrains.

It decides rather than merely executes: it can refuse to promote a newly trained
model that scores worse than the one already running, and it reports when a
category has too few examples for its score to be believed.
"""

from ml import registry, dataset
from agents.base import Agent, Decision, ACCEPT, FLAG, INFO, register

#: New labelled examples needed before a retrain is worth the time.
RETRAIN_THRESHOLD = 3
#: Below this many examples, a category's score is not worth quoting.
MIN_EXAMPLES_PER_CLASS = 8
#: A new model must not be more than this much worse to be promoted. Small
#: regressions are noise; large ones are a real loss and should be refused.
REGRESSION_TOLERANCE = 0.02


@register
class LearningAgent(Agent):
    name = "Learning Agent"
    role = "Retrains the classifiers, compares them, and decides which one runs."
    method = "5-fold cross-validated model selection"
    layer = "learning"

    def __init__(self):
        super().__init__()
        self._last_dataset_size = 0

    def decide(self, context):
        action = context.get("action", "status")
        if action == "train":
            return self._train(context)
        if action == "evaluate_need":
            return self._evaluate_need(context)
        return self._status(context)

    # -- retrain ---------------------------------------------------------
    def _train(self, context):
        previous = registry.last_results()
        previous_score = (previous["models"][0]["cv_accuracy"]
                          if previous and previous.get("models") else None)

        results = registry.train_all(
            include_learned=context.get("include_learned", True),
            folds=int(context.get("folds") or registry.CV_FOLDS),
            quick=not context.get("deep", False),
        )

        d = Decision(self.name, ACCEPT, method=self.method)
        d.data = {"results": results, "promoted": bool(results.get("promoted", True))}

        if not results.get("ok"):
            d.verdict = INFO
            d.confidence = 0.0
            d.data["promoted"] = False
            d.note(results.get("error", "Training could not run."))
            return d

        winner = results["models"][0]
        stats = results["dataset"]
        d.confidence = winner["cv_accuracy"]
        self._last_dataset_size = stats["total"]

        d.note("Trained %d models on %d examples across %d categories."
               % (len(results["models"]), stats["total"], stats["classes"]))
        d.note("Selected %s at %.1f%% cross-validated accuracy (macro F1 %.1f%%)."
               % (winner["name"], winner["cv_accuracy"] * 100, winner["macro_f1"] * 100))
        d.note(results["selection"]["reason"])

        # A drop this size is a real regression, not fold-to-fold noise.
        if previous_score is not None:
            delta = winner["cv_accuracy"] - previous_score
            d.data["delta"] = round(delta, 4)
            if delta < -REGRESSION_TOLERANCE:
                d.verdict = FLAG
                d.note("Accuracy fell %.1f points against the previous run "
                       "(%.1f%% -> %.1f%%). Recently assigned categories may "
                       "conflict with existing examples."
                       % (abs(delta) * 100, previous_score * 100,
                          winner["cv_accuracy"] * 100))
                if not results.get("promoted", True):
                    d.note("The new model was NOT promoted. %s stays live, "
                           "because a model that scores worse than the one "
                           "already running is not an improvement."
                           % results.get("kept_model", "the previous model"))
            elif delta > 0.005:
                d.note("Up %.1f points on the previous run." % (delta * 100))

        # Small classes: flag rather than quietly report a fragile number.
        thin = [c for c, n in stats["per_class"].items() if n < MIN_EXAMPLES_PER_CLASS]
        if thin:
            d.verdict = FLAG if d.verdict == ACCEPT else d.verdict
            d.note("Too few examples to trust the score for: %s (under %d each). "
                   "File a few more products under them."
                   % (", ".join(sorted(thin)), MIN_EXAMPLES_PER_CLASS))
            d.data["thin_classes"] = sorted(thin)

        if stats["balance"] < 0.4:
            d.note("The categories are unevenly sized (smallest is %.0f%% of the "
                   "largest), so macro F1 is the figure to read, not accuracy."
                   % (stats["balance"] * 100))

        weak = [c for c, m in winner["per_class"].items() if m["f1"] < 0.75]
        if weak:
            d.note("Weakest categories: %s." % ", ".join(sorted(weak)))
        for c in winner["top_confusions"][:2]:
            d.note("%s is mistaken for %s %d time(s) — the clearest thing to fix "
                   "with more examples." % (c["actual"], c["predicted"], c["count"]))
        return d

    # -- is a retrain worth it? -------------------------------------------
    def _evaluate_need(self, context):
        stats = dataset.dataset_stats()
        results = registry.last_results()
        d = Decision(self.name, INFO, method="dataset drift check")

        if results is None:
            d.verdict = ACCEPT
            d.confidence = 1.0
            d.data = {"retrain": True, "reason": "No model has been trained yet."}
            d.note("No trained model on record — training is needed before the "
                   "classifier can suggest anything.")
            return d

        trained_on = results["dataset"]["total"]
        new_examples = stats["total"] - trained_on
        should = new_examples >= RETRAIN_THRESHOLD

        d.verdict = ACCEPT if should else INFO
        d.confidence = 0.9
        d.data = {"retrain": should, "new_examples": new_examples,
                  "trained_on": trained_on, "current": stats["total"]}
        if should:
            d.note("%d new labelled example(s) since the last training run — "
                   "retraining is worthwhile." % new_examples)
        elif new_examples > 0:
            d.note("%d new example(s), below the threshold of %d. Retraining now "
                   "would cost time for no measurable gain."
                   % (new_examples, RETRAIN_THRESHOLD))
        else:
            d.note("The training data has not changed since the last run.")
        return d

    # -- status ------------------------------------------------------------
    def _status(self, context):
        summary = registry.summary()
        d = Decision(self.name, INFO, method=self.method)
        d.data = {"summary": summary, "dataset": dataset.dataset_stats()}
        if not summary.get("trained"):
            d.note("No model is loaded; one will be trained on the next request.")
            d.confidence = 0.0
            return d
        d.confidence = summary["accuracy"]
        d.note("%s is live at %.1f%% accuracy, trained on %d examples."
               % (summary["model"], summary["accuracy"] * 100, summary["samples"]))
        return d

    def fallback(self, context, error):
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"results": None, "promoted": False}
        d.note("Training could not run (%s)." % error.__class__.__name__)
        d.note("The previously selected model keeps running; nothing was replaced.")
        return d
