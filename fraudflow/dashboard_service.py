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


class LocalScorer:
    def __init__(self, path):
        path = Path(path)
        self.version = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        self.artifact = joblib.load(path)
        self.threshold = float(self.artifact['threshold'])

    def score(self, transaction):
        clean = features(pd.DataFrame([transaction]))
        score = float(self.artifact['pipeline'].predict_proba(clean)[0, 1])
        return dict(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
                    **clean.iloc[0].to_dict(), risk_score=score,
                    threshold=self.threshold, alert=score >= self.threshold,
                    model_version=self.version)


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
