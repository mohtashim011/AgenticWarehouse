"""
Common classifier interface
===========================
Every model in the zoo implements the same four methods, so the evaluation
harness can train and score them without knowing which is which — and so the
comparison in the report is genuinely like for like rather than each model being
measured on its own favourable terms.
"""

import time


class Classifier:
    #: Stable identifier used in the database and the API.
    key = "base"
    #: Human name for the dashboard.
    name = "Classifier"
    #: What the model does, in one sentence, for the report.
    description = ""
    #: The family it belongs to, for grouping.
    family = "generative"

    def __init__(self):
        self.labels = []
        self.trained = False
        self.train_ms = 0.0
        self.n_samples = 0

    # -- interface -------------------------------------------------------
    def fit(self, X, y):
        """Train on parallel lists of texts and labels."""
        raise NotImplementedError

    def predict_proba(self, text):
        """A ``{label: probability}`` dict summing to 1."""
        raise NotImplementedError

    def predict(self, text):
        """``(label, confidence)`` for the most likely class."""
        proba = self.predict_proba(text)
        if not proba:
            return None, 0.0
        label = max(proba, key=proba.get)
        return label, round(proba[label], 4)

    def predict_many(self, texts):
        return [self.predict(t)[0] for t in texts]

    # -- shared plumbing --------------------------------------------------
    def _start_fit(self, X, y):
        self.labels = sorted(set(y))
        self.n_samples = len(X)
        return time.perf_counter()

    def _end_fit(self, started):
        self.train_ms = (time.perf_counter() - started) * 1000
        self.trained = True
        return self

    def hyperparameters(self):
        """Settings worth reporting alongside the score."""
        return {}

    def info(self):
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "family": self.family,
            "trained": self.trained,
            "train_ms": round(self.train_ms, 2),
            "n_samples": self.n_samples,
            "labels": self.labels,
            "hyperparameters": self.hyperparameters(),
        }

    def explain(self, text):
        """Why the model answered as it did.

        A category the user is asked to accept should come with a reason. The
        default lists the runners-up and the margin, which is what tells someone
        whether the model was confident or merely picked one of two ties.
        """
        proba = self.predict_proba(text)
        if not proba:
            return {"top": None, "runners_up": [], "margin": 0.0, "notes": []}
        ranked = sorted(proba.items(), key=lambda kv: -kv[1])
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else (None, 0.0)
        margin = top[1] - second[1]
        notes = []
        if margin < 0.10:
            notes.append(
                "Close call between %s and %s (%.0f%% vs %.0f%%) — worth confirming."
                % (top[0], second[0], top[1] * 100, second[1] * 100))
        elif top[1] < 0.5:
            notes.append("No category stands out; the name may be unlike anything "
                         "the model has seen.")
        return {
            "top": {"label": top[0], "probability": round(top[1], 4)},
            "runners_up": [{"label": l, "probability": round(p, 4)} for l, p in ranked[1:4]],
            "margin": round(margin, 4),
            "notes": notes,
        }
