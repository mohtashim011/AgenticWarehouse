"""
Character N-Gram Naive Bayes
============================
The same probabilistic machinery as the word model, applied to overlapping runs
of characters instead of whole words.

Why bother: warehouse product names are written by suppliers, not by a style
guide. "Coffee Mug", "coffeemug", "COFFEE MUGS 350ML" and "Cofee Mug" are all
the same product, and a word model treats the last two as entirely unseen
vocabulary. Character n-grams overlap enough that a typo or a missing space
costs a little accuracy instead of all of it.

The cost is a much larger feature space — thousands of n-grams against hundreds
of words — which on a corpus this size is affordable.
"""

import math
from collections import defaultdict

from ml.features import char_ngrams, softmax
from ml.models.base import Classifier


class CharNGramNaiveBayes(Classifier):
    key = "char_ngram"
    name = "Character N-Gram Naive Bayes"
    family = "generative"
    description = ("Naive Bayes over 3-5 character n-grams. Tolerates typos, "
                   "plurals and missing spaces that defeat word-level models.")

    def __init__(self, n_min=3, n_max=5, alpha=0.35):
        super().__init__()
        self.n_min = n_min
        self.n_max = n_max
        # Lower than the word model's: with thousands of n-grams, smoothing of
        # 1.0 per feature drowns the signal entirely.
        self.alpha = alpha
        self.class_docs = defaultdict(int)
        self.class_gram = defaultdict(lambda: defaultdict(int))
        self.class_total = defaultdict(int)
        self.vocab = set()
        self.total_docs = 0

    def hyperparameters(self):
        return {
            "n_min": self.n_min, "n_max": self.n_max,
            "alpha": self.alpha, "vocabulary": len(self.vocab),
        }

    def _grams(self, text):
        return char_ngrams(text, self.n_min, self.n_max)

    def fit(self, X, y):
        started = self._start_fit(X, y)
        self.class_docs = defaultdict(int)
        self.class_gram = defaultdict(lambda: defaultdict(int))
        self.class_total = defaultdict(int)
        self.vocab = set()
        self.total_docs = 0

        for text, label in zip(X, y):
            self.class_docs[label] += 1
            self.total_docs += 1
            for gram, count in self._grams(text).items():
                self.class_gram[label][gram] += count
                self.class_total[label] += count
                self.vocab.add(gram)
        return self._end_fit(started)

    def predict_proba(self, text):
        if not self.trained or not self.labels:
            return {}
        grams = self._grams(text)
        v = len(self.vocab)
        scores = {}
        for label in self.labels:
            logp = math.log(self.class_docs[label] / self.total_docs)
            denom = self.class_total[label] + self.alpha * v
            for gram, count in grams.items():
                seen = self.class_gram[label].get(gram, 0)
                logp += count * math.log((seen + self.alpha) / denom)
            scores[label] = logp
        return softmax(scores)

    def top_terms(self, label, limit=8):
        if label not in self.class_gram:
            return []
        overall = defaultdict(int)
        for lbl in self.labels:
            for gram, count in self.class_gram[lbl].items():
                overall[gram] += count
        scored = [
            (gram, round((count / max(overall[gram], 1)) * math.log(1 + count), 4))
            for gram, count in self.class_gram[label].items()
        ]
        scored.sort(key=lambda kv: -kv[1])
        return [{"term": repr(t), "weight": w} for t, w in scored[:limit]]
