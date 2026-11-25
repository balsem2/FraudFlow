"""Local adapters: replace scoring with SageMaker and storage with DynamoDB later."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import joblib
import pandas as pd

from fraudflow.model import features
from fraudflow.investigation import FraudInvestigationAgent, configured_llm


class LocalScorer:
    def __init__(self, path, agent=None):
        path = Path(path)
        self.version = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        self.artifact = joblib.load(path)
        self.threshold = float(self.artifact['threshold'])
        self.agent = agent or FraudInvestigationAgent(configured_llm())
        self.model_factors = []
        model = self.artifact['pipeline'].named_steps['model']
        if hasattr(model, 'feature_importances_'):
            encoder = self.artifact['pipeline'].named_steps['encoding']
            from fraudflow.model import CATEGORICAL, NUMERIC
            weights = model.feature_importances_
            offset = 0
            for name, categories in zip(CATEGORICAL, encoder.named_transformers_['category'].categories_):
                self.model_factors.append(dict(feature=name, importance=float(weights[offset:offset + len(categories)].sum())))
                offset += len(categories)
            self.model_factors.extend(dict(feature=name, importance=float(weights[offset + i])) for i, name in enumerate(NUMERIC))
            self.model_factors.sort(key=lambda item: item['importance'], reverse=True)

    def score(self, transaction, context=None):
        clean = features(pd.DataFrame([transaction]))
        score = float(self.artifact['pipeline'].predict_proba(clean)[0, 1])
        result = dict(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
                    **clean.iloc[0].to_dict(), risk_score=score,
                    threshold=self.threshold, alert=score >= self.threshold,
                    model_version=self.version)
        if transaction.get('transaction_id'):
            result['transaction_id'] = transaction['transaction_id']
        if result['alert']:
            try:
                result['investigation'] = self.agent.investigate(
                    result, clean.iloc[0].to_dict(), context or transaction.get('_investigation_context'), self.model_factors[:5])
            except Exception:
                result['investigation'] = dict(status='unavailable', probable_cause='indéterminée',
                    confidence='faible', explanation='Cause probable indisponible ; décision XGBoost conservée.',
                    recommendation='Faire examiner la transaction par un analyste.', causes=[])
        return result

    def score_with_history(self, transaction, history):
        context = transaction.get('_investigation_context')
        if not isinstance(context, dict):
            context = history.context_for(transaction)
        return self.score(transaction, context)


class LocalHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS predictions '
                               '(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def add(self, record):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('INSERT INTO predictions VALUES (?, ?)',
                               (record['id'], json.dumps(record)))

    def add_batch(self, records):
        # Stable replay IDs make a retry safe; the whole batch commits together.
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany('INSERT OR IGNORE INTO predictions VALUES (?, ?)',
                                   [(row['id'], json.dumps(row)) for row in records])

    def recent(self, limit=1000):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            rows = connection.execute('SELECT payload FROM predictions '
                                      'ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def context_for(self, transaction):
        # Strictly earlier simulation days; BankSim has no trustworthy sub-day time.
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT payload FROM predictions WHERE json_extract(payload, '$.customer')=? "
                              "AND CAST(json_extract(payload, '$.step') AS REAL) < ? "
                              "ORDER BY CAST(json_extract(payload, '$.step') AS REAL) DESC LIMIT 100",
                              (str(transaction['customer']).strip("'"), float(transaction['step']))).fetchall()
        return {'history': [json.loads(row[0]) for row in rows]}
