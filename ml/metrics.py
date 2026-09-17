"""
Evaluation metrics
==================
Accuracy on its own is a poor summary of a classifier and a misleading one for
this warehouse, whose categories are not the same size. A model that always
answered "Networking" would score respectably on accuracy while being useless.

So every model is reported with:

* **accuracy** — overall share correct
* **precision / recall / F1**, per class and averaged
* **macro average** — every class counts equally, which is what matters when a
  small category is just as important to get right as a large one
* **weighted average** — classes counted by size, closer to what a user feels
* **a confusion matrix** — the only view that shows *which* categories are being
  mistaken for which, and therefore the only one that says what to fix
"""


def confusion_matrix(y_true, y_pred, labels=None):
    """``matrix[actual][predicted] = count``."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    matrix = {a: {p: 0 for p in labels} for a in labels}
    for actual, predicted in zip(y_true, y_pred):
        if actual in matrix and predicted in matrix[actual]:
            matrix[actual][predicted] += 1
    return labels, matrix


def per_class(y_true, y_pred, labels=None):
    """Precision, recall, F1 and support for each class."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    out = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
        }
    return out


def accuracy(y_true, y_pred):
    if not y_true:
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


def report(y_true, y_pred, labels=None):
    """The full evaluation of one model on one set of predictions."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    classes = per_class(y_true, y_pred, labels)
    matrix_labels, matrix = confusion_matrix(y_true, y_pred, labels)
    n = len(y_true) or 1

    macro = {
        metric: round(sum(c[metric] for c in classes.values()) / (len(classes) or 1), 4)
        for metric in ("precision", "recall", "f1")
    }
    weighted = {
        metric: round(
            sum(c[metric] * c["support"] for c in classes.values()) / n, 4)
        for metric in ("precision", "recall", "f1")
    }

    return {
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "samples": len(y_true),
        "correct": sum(1 for t, p in zip(y_true, y_pred) if t == p),
        "labels": labels,
        "per_class": classes,
        "macro": macro,
        "weighted": weighted,
        "confusion": {"labels": matrix_labels, "matrix": matrix},
        "top_confusions": top_confusions(matrix, matrix_labels),
    }


def top_confusions(matrix, labels, limit=5):
    """The most frequent wrong answers.

    This is the actionable part of an evaluation: "Glassware is being called
    Coffee Mugs four times" tells you which examples to add next, in a way that
    a single accuracy figure never can.
    """
    pairs = []
    for actual in labels:
        for predicted in labels:
            if actual != predicted and matrix[actual][predicted]:
                pairs.append({
                    "actual": actual,
                    "predicted": predicted,
                    "count": matrix[actual][predicted],
                })
    pairs.sort(key=lambda p: -p["count"])
    return pairs[:limit]


def mean_std(values):
    """Mean and sample standard deviation — the spread across CV folds.

    A model that scores 0.90 +/- 0.02 is meaningfully better than one that
    scores 0.90 +/- 0.15, and reporting only the mean hides that entirely.
    """
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, var ** 0.5
