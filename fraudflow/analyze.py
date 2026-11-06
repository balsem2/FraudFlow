"""Produce a reproducible dataset quality report before training."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from fraudflow.model import CATEGORICAL, features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--output', default='artifacts/data_report.json')
    args = parser.parse_args()
    source = Path(args.data)
    data = pd.read_csv(source)
    clean = features(data)
    if not data['fraud'].isin([0, 1]).all():
        raise ValueError('Invalid fraud labels')
    categories = {}
    for column in CATEGORICAL:
        grouped = clean.assign(fraud=data['fraud']).groupby(column)['fraud']
        categories[column] = grouped.agg(['count', 'sum', 'mean']).to_dict('index')
    report = {
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'rows': len(data), 'columns': data.columns.tolist(),
        'missing_values': data.isna().sum().to_dict(),
        'duplicate_rows': int(data.duplicated().sum()),
        'fraud_count': int(data['fraud'].sum()),
        'fraud_rate': float(data['fraud'].mean()),
        'step_min': int(data['step'].min()),
        'step_max': int(data['step'].max()),
        'step_count': int(data['step'].nunique()),
        'amount_summary': clean['amount'].describe().to_dict(),
        'categories': categories,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
