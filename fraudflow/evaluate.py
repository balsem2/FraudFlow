"""Re-evaluate the saved model on the recorded split, without fitting it."""
import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from fraudflow.model import features
from fraudflow.train import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data/banksim.csv')
    parser.add_argument('--artifacts', default='artifacts')
    args = parser.parse_args()
    directory = Path(args.artifacts)
    artifact = joblib.load(directory / 'model.joblib')
    metrics_path = directory / 'metrics.json'
    metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
    if artifact['threshold'] != metrics['threshold']:
        raise ValueError('Model and metrics thresholds differ.')
    data = pd.read_csv(args.data)
    test = data['step'] >= metrics['test_start_step']
    validation = ((data['step'] >= metrics['validation_start_step']) & ~test)
    for name, mask in [('test', test), ('validation', validation)]:
        if int(mask.sum()) != metrics[f'{name}_rows']:
            raise ValueError(f'{name} row count differs from training report.')
        labels = data.loc[mask, 'fraud']
        if set(labels.unique()) != {0, 1}:
            raise ValueError('Expected both binary classes.')
        scores = artifact['pipeline'].predict_proba(features(data.loc[mask]))[:, 1]
        result = evaluate(labels, scores, artifact['threshold'])
        if name == 'test':
            metrics.update(result)
            metrics['test_at_threshold_0_5'] = evaluate(labels, scores, 0.5)
        else:
            metrics['validation'] = result
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
