"""
The model zoo
=============
Five classifiers competing on the same task, each with a different view of what
a product name is. They share the :class:`~ml.models.base.Classifier` interface
so the evaluation harness can treat them interchangeably and the comparison is
genuinely like for like.
"""

from ml.models.base import Classifier
from ml.models.naive_bayes import MultinomialNaiveBayes
from ml.models.logistic import TfidfLogisticRegression
from ml.models.char_ngram import CharNGramNaiveBayes
from ml.models.knn import TfidfKNN
from ml.models.centroid import NearestCentroid

#: Every model the bake-off trains, in a stable order.
ALL_MODELS = [
    MultinomialNaiveBayes,
    TfidfLogisticRegression,
    CharNGramNaiveBayes,
    TfidfKNN,
    NearestCentroid,
]


def build_all():
    """A fresh, untrained instance of every model."""
    return [cls() for cls in ALL_MODELS]


def build(key):
    """One model by its key, or None."""
    for cls in ALL_MODELS:
        if cls.key == key:
            return cls()
    return None


__all__ = [
    "Classifier", "MultinomialNaiveBayes", "TfidfLogisticRegression",
    "CharNGramNaiveBayes", "TfidfKNN", "NearestCentroid",
    "ALL_MODELS", "build_all", "build",
]
