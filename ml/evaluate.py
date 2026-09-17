"""
Evaluation harness
==================
How the models are measured, and why it is done this way.

**Stratified splits.** Folds keep each category's share of the data. With six
categories and a few dozen examples each, a random split can easily hand a fold
no Coffee Mugs at all — and a model then scores a perfect zero on a class it was
never shown, which says nothing about the model.

**k-fold cross-validation.** Every example is used for testing exactly once, so
the score does not depend on which slice happened to be held out. The standard
deviation across folds is reported next to the mean, because a model that swings
wildly between folds has not really learned the task.

**A fixed seed.** Re-running training must not quietly change the numbers in the
report. Anyone re-running this should get the figures they read.

**Nothing leaks.** The vectoriser is fitted inside each fold, on the training
half only. Fitting it once on everything first would let test-set vocabulary
inform the IDF weights and inflate every score — a mistake that is easy to make
and produces results that look excellent and mean nothing.
"""

import random

from ml import metrics


def stratified_folds(y, k=5, seed=42):
    """Indices for k folds that preserve each class's proportion."""
    by_class = {}
    for i, label in enumerate(y):
        by_class.setdefault(label, []).append(i)

    rng = random.Random(seed)
    folds = [[] for _ in range(k)]
    for label in sorted(by_class):
        indices = by_class[label][:]
        rng.shuffle(indices)
        # Deal each class round-robin so the remainder spreads across folds
        # instead of piling onto the last one.
        for position, index in enumerate(indices):
            folds[position % k].append(index)
    return folds


def stratified_split(X, y, test_size=0.25, seed=42):
    """A single stratified train/test split."""
    by_class = {}
    for i, label in enumerate(y):
        by_class.setdefault(label, []).append(i)

    rng = random.Random(seed)
    test = []
    for label in sorted(by_class):
        indices = by_class[label][:]
        rng.shuffle(indices)
        # At least one test example per class, so no class is silently skipped.
        n_test = max(1, int(round(len(indices) * test_size)))
        test.extend(indices[:n_test])

    test_set = set(test)
    train = [i for i in range(len(X)) if i not in test_set]
    return (
        [X[i] for i in train], [y[i] for i in train],
        [X[i] for i in test], [y[i] for i in test],
    )


def cross_validate(model_factory, X, y, k=5, seed=42):
    """k-fold cross-validation for one model.

    ``model_factory`` is called per fold so each one trains a genuinely fresh
    model — reusing an instance would leave the previous fold's parameters in
    place and quietly turn this into a test on training data.
    """
    labels = sorted(set(y))
    folds = stratified_folds(y, k, seed)

    fold_scores = []
    all_true, all_pred = [], []
    train_ms = []

    for f in range(k):
        test_idx = folds[f]
        train_idx = [i for j, fold in enumerate(folds) if j != f for i in fold]
        if not test_idx or not train_idx:
            continue

        model = model_factory()
        model.fit([X[i] for i in train_idx], [y[i] for i in train_idx])
        train_ms.append(model.train_ms)

        y_true = [y[i] for i in test_idx]
        y_pred = [model.predict(X[i])[0] for i in test_idx]

        fold_scores.append(metrics.accuracy(y_true, y_pred))
        all_true.extend(y_true)
        all_pred.extend(y_pred)

    mean, std = metrics.mean_std(fold_scores)
    # Pooling every fold's predictions gives one confusion matrix over the whole
    # dataset, which is far more readable than k separate small ones.
    pooled = metrics.report(all_true, all_pred, labels)

    return {
        "folds": k,
        "fold_accuracies": [round(s, 4) for s in fold_scores],
        "cv_accuracy": round(mean, 4),
        "cv_std": round(std, 4),
        "cv_min": round(min(fold_scores), 4) if fold_scores else 0.0,
        "cv_max": round(max(fold_scores), 4) if fold_scores else 0.0,
        "avg_train_ms": round(sum(train_ms) / len(train_ms), 2) if train_ms else 0.0,
        "pooled": pooled,
    }


def leave_one_out(model_factory, X, y):
    """Leave-one-out cross-validation.

    The most thorough option and the most expensive: it trains one model per
    example. Reported because the original MVP quoted a leave-one-out figure,
    and a comparison against it has to be measured the same way to be fair.
    """
    labels = sorted(set(y))
    y_true, y_pred = [], []
    for i in range(len(X)):
        model = model_factory()
        model.fit([X[j] for j in range(len(X)) if j != i],
                  [y[j] for j in range(len(X)) if j != i])
        y_true.append(y[i])
        y_pred.append(model.predict(X[i])[0])
    return metrics.report(y_true, y_pred, labels)


def holdout_evaluate(model_factory, X, y, test_size=0.25, seed=42):
    """Train on one split and report on the held-out remainder."""
    X_train, y_train, X_test, y_test = stratified_split(X, y, test_size, seed)
    model = model_factory()
    model.fit(X_train, y_train)
    y_pred = [model.predict(t)[0] for t in X_test]
    result = metrics.report(y_test, y_pred, sorted(set(y)))
    result["train_size"] = len(X_train)
    result["test_size"] = len(X_test)
    result["train_ms"] = round(model.train_ms, 2)
    # Keep the misses: "which names did it actually get wrong" is the question
    # everyone asks first, and a matrix alone cannot answer it.
    result["errors"] = [
        {"text": text, "actual": actual, "predicted": predicted}
        for text, actual, predicted in zip(X_test, y_test, y_pred)
        if actual != predicted
    ][:20]
    return result, model
