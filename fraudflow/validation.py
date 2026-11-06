"""Chronological partitions and threshold selection without test labels."""
import numpy as np
from sklearn.metrics import precision_recall_curve


def chronological_split(steps):
    unique = np.sort(steps.unique())
    if len(unique) < 5:
        raise ValueError('Au moins cinq steps distincts sont nécessaires.')
    validation_start = unique[int(len(unique) * 0.6)]
    test_start = unique[int(len(unique) * 0.8)]
    return (steps < validation_start,
            (steps >= validation_start) & (steps < test_start),
            steps >= test_start)


def select_threshold(labels, scores):
    """Maximize validation F1; prefer higher threshold on exact ties."""
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(2 * precision[:-1] * recall[:-1], denominator,
                   out=np.zeros_like(denominator), where=denominator > 0)
    best = np.flatnonzero(f1 == f1.max())[-1]
    return float(thresholds[best])
