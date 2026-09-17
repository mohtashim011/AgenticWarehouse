"""
Classifier Agent
================
Decides which category a product belongs to — or, more often, decides that it is
not its place to say.

The rule that matters
---------------------
**The user's own assignment always wins.** A category a manager has filed is
fact; a category the model produced is an opinion. An unseen product is filed as
``Uncategorised`` with a *suggestion* attached, which a person accepts or
overrides. The model never writes a category straight into inventory, because a
wrong guess sitting in the stock table is indistinguishable from a fact and
nobody goes back to check it.

What changed
------------
The model behind the suggestion is no longer a single hard-coded Naive Bayes.
:mod:`ml.registry` trains five classifiers, cross-validates them, and this agent
asks for whichever won. On the current corpus that is a jump from 70% to 93.7%,
and it will move again as managers file more products — which is the point.
"""

import db
from ml import registry
from agents.base import Agent, Decision, ACCEPT, INFO, register

UNCATEGORISED = "Uncategorised"

#: A suggestion below this is not worth putting in front of someone: acting on
#: it is a coin toss, and a bad suggestion costs more attention than none.
MIN_SUGGESTION_CONFIDENCE = 0.35


@register
class ClassifierAgent(Agent):
    name = "Classifier Agent"
    role = "Suggests a category for an unseen product; never overrides the user."
    method = "cross-validated model selection over five classifiers"
    layer = "perception"

    def decide(self, context):
        name = context.get("name")
        catalog_hint = context.get("catalog_hint")
        known_categories = context.get("known_categories") or []

        # 1. The user has already filed this product. Nothing to decide.
        if catalog_hint:
            d = Decision(self.name, ACCEPT, 1.0, method="user-assigned category")
            d.data = {"category": catalog_hint, "suggestion": None,
                      "source": "user"}
            d.note("'%s' is filed under %s by you." % (name, catalog_hint))
            d.note("A category you assigned is never overridden by the model.")
            return d

        # 2. A bare barcode carries no name, so there is nothing to classify.
        if not name or name == db.UNKNOWN_NAME:
            d = Decision(self.name, INFO, 0.0, method="no name to classify")
            d.data = {"category": UNCATEGORISED, "suggestion": None,
                      "source": "none"}
            d.note("No product name to classify (barcode-only item).")
            d.note("Name the product first, then a category can be suggested.")
            return d

        # 3. An unseen name: suggest, but file it as Uncategorised.
        model = registry.active_model()
        if model is None:
            d = Decision(self.name, INFO, 0.0, method="no model available")
            d.data = {"category": UNCATEGORISED, "suggestion": None, "source": "none"}
            d.note("No classifier is trained yet, so no suggestion can be made.")
            return d

        label, confidence = model.predict(name)
        explanation = model.explain(name)

        # Only ever suggest a category that actually exists for the user to pick.
        if known_categories and label not in known_categories:
            label, confidence = None, 0.0
        if confidence < MIN_SUGGESTION_CONFIDENCE:
            label, confidence = None, confidence

        d = Decision(self.name, INFO, confidence,
                     method="%s (%.0f%% cross-validated)"
                            % (model.name, _accuracy() * 100))
        d.data = {
            "category": UNCATEGORISED,
            "source": "model",
            "model": model.name,
            "suggestion": ({"category": label, "confidence": round(confidence, 2)}
                           if label else None),
            "alternatives": explanation.get("runners_up", [])[:2],
        }
        d.note("'%s' has no category assigned yet — filed as %s."
               % (name, UNCATEGORISED))
        if label:
            d.note("Suggestion: %s (%.0f%% confident). Accept or change it in the "
                   "Categories panel." % (label, confidence * 100))
            for note in explanation.get("notes", []):
                d.note(note)
            alts = explanation.get("runners_up", [])[:2]
            if alts:
                d.note("Next most likely: %s." % ", ".join(
                    "%s %.0f%%" % (a["label"], a["probability"] * 100) for a in alts))
        else:
            d.note("No category was likely enough to suggest — this name is "
                   "unlike anything the model has been shown.")
        return d

    def fallback(self, context, error):
        """A classifier failure must never block a scan.

        Categorisation is advisory; receiving stock is not. If the model breaks,
        the product is filed as Uncategorised and the scan proceeds.
        """
        d = Decision(self.name, INFO, 0.0, method="unavailable", degraded=True)
        d.data = {"category": UNCATEGORISED, "suggestion": None, "source": "none"}
        d.note("The classifier is unavailable (%s)." % error.__class__.__name__)
        d.note("Filed as %s; the scan was not affected." % UNCATEGORISED)
        return d


def _accuracy():
    summary = registry.summary()
    return summary.get("accuracy", 0.0) if summary.get("trained") else 0.0


# ---------------------------------------------------------------------------
# Backwards-compatible function interface
# ---------------------------------------------------------------------------
def run(name, catalog_hint=None, known_categories=None):
    """The shape the orchestrator has always called.

    Kept so the pipeline and its tests continue to work unchanged while the
    machinery underneath moved to the agent framework.
    """
    decision = ClassifierAgent.instance.run({
        "name": name,
        "catalog_hint": catalog_hint,
        "known_categories": known_categories,
    })
    out = decision.to_dict()
    # The old contract used 'notes'; the framework calls it 'rationale'.
    out["notes"] = out.get("rationale", [])
    return out
