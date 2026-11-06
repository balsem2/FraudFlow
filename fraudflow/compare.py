"""Compare three fixed baselines on validation; never score or tune on test."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
import warnings

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from fraudflow.model import CATEGORICAL, NUMERIC, FEATURES, features, pipeline
from fraudflow.train import evaluate
from fraudflow.validation import chronological_split, select_threshold


def candidates():
    logistic = Pipeline([
        ('encoding', ColumnTransformer([
            ('category', OneHotEncoder(handle_unknown='ignore'), CATEGORICAL),
            ('numeric', StandardScaler(), NUMERIC),
        ])),
        ('model', LogisticRegression(solver='lbfgs', max_iter=2000, C=1.0)),
    ])
    forest = pipeline()
    forest.set_params(model=RandomForestClassifier(
        n_estimators=200, max_depth=16, min_samples_leaf=2,
        max_features='sqrt', random_state=42, n_jobs=2))
    return {'LogisticRegression': logistic, 'RandomForest': forest, 'XGBoost': pipeline()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data/banksim.csv')
    parser.add_argument('--output', default='artifacts/comparison')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(args.data)
    data = pd.read_csv(source)
    train, validation, test = chronological_split(data.step)
    x = features(data)
    y = data.fraud
    if not y.isin([0, 1]).all() or any(y[mask].nunique() != 2 for mask in (train, validation)):
        raise ValueError('Expected both binary classes in train and validation.')
    report = dict(dataset_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  selection='Highest validation average_precision; no test evaluation',
                  train_rows=int(train.sum()), validation_rows=int(validation.sum()),
                  reserved_test_rows=int(test.sum()), features=FEATURES, models={})
    for name, model in candidates().items():
        print(f'Training {name}...', flush=True)
        start = perf_counter()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ConvergenceWarning)
            model.fit(x[train], y[train])
        fit_seconds = perf_counter() - start
        start = perf_counter()
        scores = model.predict_proba(x[validation])[:, 1]
        predict_seconds = perf_counter() - start
        threshold = select_threshold(y[validation], scores)
        result = evaluate(y[validation], scores, threshold)
        result.update(threshold=threshold, fit_seconds=fit_seconds,
                      validation_predict_seconds=predict_seconds,
                      converged=not any(issubclass(w.category, ConvergenceWarning) for w in caught),
                      warnings=[str(w.message) for w in caught],
                      estimator_params={k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                                        for k, v in model.named_steps['model'].get_params().items()})
        report['models'][name] = result
        joblib.dump(dict(pipeline=model, threshold=threshold, features=FEATURES), output / f'{name}.joblib')
        (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k: result[k] for k in ['average_precision', 'precision', 'recall', 'f1', 'fit_seconds', 'converged']}), flush=True)
    eligible = [name for name, result in report['models'].items() if result['converged']]
    report['winner'] = max(eligible, key=lambda name: report['models'][name]['average_precision'])
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Winner on validation average precision: {report['winner']}", flush=True)


if __name__ == '__main__':
    main()
