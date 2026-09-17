"""
TF-IDF k-Nearest Neighbours
===========================
No training in the usual sense: the model keeps every example and classifies a
new name by finding the ones most like it.

Its appeal here is practical rather than statistical. When a manager files a new
product under a category, kNN can use that the very next scan — there is no
retraining step to wait for. It is also the easiest model to explain to someone
who does not want a probability: *"this looks like these three things you
already filed under Glassware."*

Neighbours vote by similarity rather than one-vote-each, so a near-identical
name counts for much more than a distant one that happened to make the top k.
"""

from ml.features import TfidfVectorizer, tokenize, cosine
from ml.models.base import Classifier


class TfidfKNN(Classifier):
    key = "tfidf_knn"
    name = "TF-IDF k-Nearest Neighbours"
    family = "instance-based"
    description = ("Classifies by cosine similarity to the most similar known "
                   "products. Learns a new category the moment one is assigned, "
                   "with no retraining.")

    def __init__(self, k=5):
        super().__init__()
        self.k = k
        self.vectorizer = TfidfVectorizer(analyzer=tokenize)
        self.vectors = []
        self.targets = []
        self.texts = []

    def hyperparameters(self):
        return {"k": self.k, "stored_examples": len(self.vectors),
                "vocabulary": len(self.vectorizer.vocabulary)}

    def fit(self, X, y):
        started = self._start_fit(X, y)
        self.vectors = self.vectorizer.fit_transform(X)
        self.targets = list(y)
        self.texts = list(X)
        return self._end_fit(started)

    def _neighbours(self, text):
        query = self.vectorizer.transform(text)
        if not query:
            return []
        scored = [
            (cosine(query, vec), self.targets[i], self.texts[i])
            for i, vec in enumerate(self.vectors)
        ]
        scored.sort(key=lambda s: -s[0])
        return scored[:self.k]

    def predict_proba(self, text):
        if not self.trained or not self.labels:
            return {}
        neighbours = self._neighbours(text)
        votes = {label: 0.0 for label in self.labels}
        total = 0.0
        for similarity, label, _ in neighbours:
            if similarity <= 0:
                continue
            # Squaring sharpens the difference between a close match and a
            # merely plausible one; without it, five weak neighbours outvote
            # one excellent match.
            weight = similarity ** 2
            votes[label] = votes.get(label, 0.0) + weight
            total += weight
        if total == 0:
            # Nothing resembled the query at all. A uniform answer is the honest
            # response — better than a confident guess from an empty vote.
            uniform = 1.0 / len(self.labels)
            return {label: uniform for label in self.labels}
        return {label: v / total for label, v in votes.items()}

    def explain(self, text):
        """Which stored products drove the answer."""
        base = super().explain(text)
        base["neighbours"] = [
            {"text": t, "label": l, "similarity": round(s, 4)}
            for s, l, t in self._neighbours(text) if s > 0
        ]
        return base
