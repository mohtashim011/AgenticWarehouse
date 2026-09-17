"""
Feature extraction
==================
Turning a product name into numbers the models can work with.

Three representations, because the four classifiers disagree about what matters
in a product name and the comparison is more interesting when they genuinely
differ:

* **word tokens** — the obvious one, and what Naive Bayes wants
* **TF-IDF vectors** — words weighted by how much they distinguish a class,
  so "cable" (everywhere) counts for less than "gpon" (one class only)
* **character n-grams** — robust to the typos, plurals and glued-together words
  that supplier names are full of; "mug" is still found inside "coffeemug"

Everything is plain dicts and lists. A sparse vector is a ``{term: weight}``
dict, which for names of a dozen words is both faster and clearer than carrying
a dense array around.
"""

import math
import re

_WORD = re.compile(r"[a-z0-9]+")

# Words that appear across every category and carry no signal about which one.
# Sizes are deliberately NOT stripped: "225ml" is a genuinely useful hint that
# something is a drinking vessel rather than a network switch.
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "with", "to", "in", "on",
    "set", "pack", "piece", "pcs", "unit", "units", "item", "new", "type",
}


def tokenize(text):
    """Lower-case word tokens, minus stopwords."""
    return [t for t in _WORD.findall((text or "").lower()) if t not in STOPWORDS]


def bag_of_words(text):
    """Term counts."""
    counts = {}
    for t in tokenize(text):
        counts[t] = counts.get(t, 0) + 1
    return counts


def char_ngrams(text, n_min=3, n_max=5):
    """Character n-gram counts, with word boundaries marked.

    Padding each word with spaces means a prefix or suffix is a distinct feature
    from the same letters mid-word — "mug " at the end of a name is a far
    stronger signal than "mug" buried inside "mugginess".
    """
    cleaned = " ".join(tokenize(text))
    if not cleaned:
        return {}
    padded = " %s " % cleaned
    grams = {}
    for n in range(n_min, n_max + 1):
        for i in range(len(padded) - n + 1):
            g = padded[i:i + n]
            grams[g] = grams.get(g, 0) + 1
    return grams


# ---------------------------------------------------------------------------
# TF-IDF
# ---------------------------------------------------------------------------
class TfidfVectorizer:
    """Sublinear TF x smoothed IDF, L2-normalised.

    Written out rather than imported so every choice is visible:

    * **sublinear tf** (``1 + log(count)``) — a name that says "cable" twice is
      not twice as much about cables.
    * **smoothed idf** — the ``+1`` terms keep an unseen document count from
      dividing by zero.
    * **L2 normalisation** — so a long product name does not outweigh a short
      one purely by having more words in it.
    """

    def __init__(self, analyzer=tokenize, min_df=1):
        self.analyzer = analyzer
        self.min_df = min_df
        self.idf = {}
        self.vocabulary = []

    def fit(self, documents):
        doc_freq = {}
        for doc in documents:
            for term in set(self.analyzer(doc)):
                doc_freq[term] = doc_freq.get(term, 0) + 1
        n = len(documents) or 1
        self.idf = {
            term: math.log((1 + n) / (1 + df)) + 1.0
            for term, df in doc_freq.items() if df >= self.min_df
        }
        self.vocabulary = sorted(self.idf)
        return self

    def transform(self, document):
        counts = {}
        for term in self.analyzer(document):
            if term in self.idf:
                counts[term] = counts.get(term, 0) + 1
        vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in counts.items()}
        return l2_normalize(vec)

    def fit_transform(self, documents):
        self.fit(documents)
        return [self.transform(d) for d in documents]


def l2_normalize(vec):
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0:
        return dict(vec)
    return {k: v / norm for k, v in vec.items()}


def dot(a, b):
    """Sparse dot product; iterate the shorter side."""
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def cosine(a, b):
    """Cosine similarity of two sparse vectors."""
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot(a, b) / (na * nb)


def softmax(scores):
    """Turn raw scores into probabilities that sum to 1.

    The maximum is subtracted first: without it, ``exp`` of a large log-score
    overflows, which is exactly what happens with a confident Naive Bayes on a
    long product name.
    """
    if not scores:
        return {}
    mx = max(scores.values())
    exps = {k: math.exp(v - mx) for k, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}
