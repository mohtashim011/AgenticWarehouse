"""
Nearest Centroid (Rocchio)
==========================
Averages every training example of a category into a single prototype vector,
then classifies a name by whichever prototype it sits closest to.

The simplest model in the line-up and the cheapest to run: one vector per
category rather than one per example, so it stays fast no matter how large the
catalogue grows.

It is in the comparison because it is a genuinely useful control. Nearest
centroid tends to do well precisely when categories are compact and well
separated. If it keeps pace with logistic regression, the task is easier than it
looks; if it falls behind, the categories really do overlap and the extra
machinery is earning its place.
"""

from ml.features import TfidfVectorizer, tokenize, cosine, l2_normalize, softmax
from ml.models.base import Classifier


class NearestCentroid(Classifier):
    key = "nearest_centroid"
    name = "Nearest Centroid (Rocchio)"
    family = "prototype"
    description = ("Builds one average TF-IDF prototype per category and picks "
                   "the closest. Very fast, and a fair control for whether the "
                   "heavier models are earning their keep.")

    def __init__(self, sharpness=6.0):
        super().__init__()
        #: Scales cosine similarities before the softmax. Raw cosines sit in a
        #: narrow band, so without this every prediction reads as ~equally
        #: likely and the confidence figure becomes meaningless.
        self.sharpness = sharpness
        self.vectorizer = TfidfVectorizer(analyzer=tokenize)
        self.centroids = {}

    def hyperparameters(self):
        return {"sharpness": self.sharpness,
                "centroids": len(self.centroids),
                "vocabulary": len(self.vectorizer.vocabulary)}

    def fit(self, X, y):
        started = self._start_fit(X, y)
        vectors = self.vectorizer.fit_transform(X)

        sums = {label: {} for label in self.labels}
        counts = {label: 0 for label in self.labels}
        for vec, label in zip(vectors, y):
            acc = sums[label]
            for term, value in vec.items():
                acc[term] = acc.get(term, 0.0) + value
            counts[label] += 1

        self.centroids = {}
        for label, acc in sums.items():
            n = counts[label] or 1
            self.centroids[label] = l2_normalize({t: v / n for t, v in acc.items()})
        return self._end_fit(started)

    def predict_proba(self, text):
        if not self.trained or not self.centroids:
            return {}
        query = self.vectorizer.transform(text)
        if not query:
            uniform = 1.0 / len(self.labels)
            return {label: uniform for label in self.labels}
        scores = {label: cosine(query, c) * self.sharpness
                  for label, c in self.centroids.items()}
        return softmax(scores)

    def top_terms(self, label, limit=8):
        """The terms that define a category's prototype."""
        centroid = self.centroids.get(label)
        if not centroid:
            return []
        ranked = sorted(centroid.items(), key=lambda kv: -kv[1])
        return [{"term": t, "weight": round(w, 4)} for t, w in ranked[:limit]]
