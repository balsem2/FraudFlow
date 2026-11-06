"""Train on earlier steps; evaluate once on later steps."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

from fraudflow.model import FEATURES, features, pipeline
from fraudflow.validation import chronological_split, select_threshold


def evaluate(labels, scores, threshold):
    predictions = scores >= threshold
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "always_normal_accuracy": float(np.mean(np.asarray(labels) == 0)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "average_precision": float(average_precision_score(labels, scores)),
        "confusion_matrix_labels_0_1": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", default="artifacts")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Seuil fixe facultatif ; sinon maximiser F1 sur validation.")
    args = parser.parse_args()
    if args.threshold is not None and not 0 < args.threshold < 1:
        parser.error("threshold doit être entre 0 et 1 (exclus).")
    data = pd.read_csv(args.data)
    x = features(data)
    y = pd.to_numeric(data["fraud"], errors="raise")
    steps = pd.to_numeric(data["step"], errors="raise")
    if not y.isin([0, 1]).all() or not np.isfinite(steps).all():
        raise ValueError("Labels fraud invalides ou steps non finis.")
    train, validation, test = chronological_split(steps)
    if any(y[mask].nunique() != 2 for mask in (train, validation, test)):
        raise ValueError("Chaque partition doit contenir les deux classes.")
    model = pipeline()
    model.fit(x[train], y[train])
    validation_scores = model.predict_proba(x[validation])[:, 1]
    threshold = (select_threshold(y[validation], validation_scores)
                 if args.threshold is None else args.threshold)
    # Freeze model and threshold before evaluating test; do not refit on validation.
    scores = model.predict_proba(x[test])[:, 1]
    metrics = {
        "features": FEATURES,
        "train_rows": int(train.sum()), "test_rows": int(test.sum()),
        "validation_rows": int(validation.sum()),
        "validation_start_step": int(steps[validation].min()),
        "test_start_step": int(steps[test].min()), "fraud_rate": float(y.mean()),
        "threshold": threshold,
        "threshold_selection": "validation_max_f1" if args.threshold is None else "fixed",
        "evaluation_note": "Exploratory: test period was inspected in previous experiments.",
        "validation": evaluate(y[validation], validation_scores, threshold),
        "test_at_threshold_0_5": evaluate(y[test], scores, 0.5),
        **evaluate(y[test], scores, threshold),
        "test_fraud_rate": float(y[test].mean()),
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": model, "threshold": threshold, "features": FEATURES}, output / "model.joblib")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
