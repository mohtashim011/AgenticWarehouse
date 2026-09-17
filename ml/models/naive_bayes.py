"""
Multinomial Naive Bayes
=======================
The baseline, and the model the original MVP shipped with.

Estimates ``P(category | name)`` from word counts, assuming each word is
independent given the category. That assumption is plainly false for product
names — "optical" and "fiber" travel together — yet the model works well anyway,
which is the usual and slightly unreasonable story with Naive Bayes.

Kept in the line-up because it trains in milliseconds, needs very little data,
and gives the other four something honest to beat.
"""

import math
from collections import defaultdict

from ml.features import tokenize, softmax
from ml.models.base import Classifier


class MultinomialNaiveBayes(Classifier):
    key = "naive_bayes"
    name = "Multinomial Naive Bayes"
    family = "generative"
    description = ("Word-count probabilities per category with Laplace smoothing. "
                   "Fast, interpretable, and strong on small datasets.")

    def __init__(self, alpha=1.0):
        super().__init__()
        #: Laplace smoothing. Stops a single unseen word driving the whole
        #: posterior to zero, which is what makes the model usable at all.
        self.alpha = alpha
        self.class_docs = defaultdict(int)
        self.class_word = defaultdict(lambda: defaultdict(int))
        self.class_total = defaultdict(int)
        self.vocab = set()
        self.total_docs = 0

    def hyperparameters(self):
        return {"alpha": self.alpha, "vocabulary": len(self.vocab)}

    def fit(self, X, y):
        started = self._start_fit(X, y)
        self.class_docs = defaultdict(int)
        self.class_word = defaultdict(lambda: defaultdict(int))
        self.class_total = defaultdict(int)
        self.vocab = set()
        self.total_docs = 0

        for text, label in zip(X, y):
            self.class_docs[label] += 1
            self.total_docs += 1
            for token in tokenize(text):
                self.class_word[label][token] += 1
                self.class_total[label] += 1
                self.vocab.add(token)
        return self._end_fit(started)

    def predict_proba(self, text):
        if not self.trained or not self.labels:
            return {}
        tokens = tokenize(text)
        v = len(self.vocab)
        scores = {}
        for label in self.labels:
            # Work in logs: multiplying a dozen small probabilities in floating
            # point underflows to zero surprisingly quickly.
            logp = math.log(self.class_docs[label] / self.total_docs)
            denom = self.class_total[label] + self.alpha * v
            for token in tokens:
                count = self.class_word[label].get(token, 0)
                logp += math.log((count + self.alpha) / denom)
            scores[label] = logp
        return softmax(scores)

    def top_terms(self, label, limit=8):
        """The words that most distinguish a category.

        Ranked by how much more often a word appears in this class than across
        the corpus, so common words like "cable" do not crowd out the ones that
        actually carry the decision.
        """
        if label not in self.class_word:
            return []
        overall = defaultdict(int)
        for lbl in self.labels:
            for term, count in self.class_word[lbl].items():
                overall[term] += count
        scored = []
        for term, count in self.class_word[label].items():
            share = count / max(overall[term], 1)
            scored.append((term, round(share * math.log(1 + count), 4)))
        scored.sort(key=lambda kv: -kv[1])
        return [{"term": t, "weight": w} for t, w in scored[:limit]]
