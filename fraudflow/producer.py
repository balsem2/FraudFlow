"""Standalone local replay with atomic SQLite checkpoints (no browser required)."""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import threading

from fraudflow.dashboard_service import LocalHistory, LocalScorer
from fraudflow.replay import load_transactions
from fraudflow.investigation import FraudInvestigationAgent


class Producer:
    def __init__(self, data, scorer, history, run_id, fingerprint):
        self.data, self.scorer, self.history = data, scorer, history
        self.run_id = run_id
        with closing(sqlite3.connect(history.path, timeout=30)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS producer_runs '
                       '(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, cursor INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO producer_runs VALUES (?, ?, 0)', (run_id, fingerprint))
            stored = db.execute('SELECT fingerprint FROM producer_runs WHERE id=?', (run_id,)).fetchone()[0]
            if stored != fingerprint:
                raise ValueError('Dataset ou modèle modifié : utiliser un nouveau --run-id.')

    @property
    def cursor(self):
        with closing(sqlite3.connect(self.history.path, timeout=30)) as db:
            return db.execute('SELECT cursor FROM producer_runs WHERE id=?', (self.run_id,)).fetchone()[0]

    def tick(self, size):
        if size < 1:
            raise ValueError('La taille du lot doit être positive.')
        cursor = self.cursor
        records = []
        for position, transaction in enumerate(self.data.iloc[cursor:cursor + size].to_dict('records'), cursor):
            record = (self.scorer.score_with_history(transaction, self.history)
                      if hasattr(self.scorer, 'score_with_history') else self.scorer.score(transaction))
            record.update(id=f'producer:{self.run_id}:{position}', source='independent_producer',
                          replay_run=self.run_id)
            records.append(record)
        with closing(sqlite3.connect(self.history.path, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT cursor FROM producer_runs WHERE id=?', (self.run_id,)).fetchone()[0]
            if current != cursor:
                return current  # Another worker already committed this batch.
            db.executemany('INSERT INTO predictions VALUES (?, ?)',
                           [(r['id'], json.dumps(r)) for r in records])
            db.execute('UPDATE producer_runs SET cursor=? WHERE id=?', (cursor + len(records), self.run_id))
        return cursor + len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=os.getenv('FRAUDFLOW_DATA_PATH', 'data/banksim.csv'))
    parser.add_argument('--model', default=os.getenv('FRAUDFLOW_MODEL_PATH', 'artifacts/model.joblib'))
    parser.add_argument('--db', default=os.getenv('FRAUDFLOW_DB_PATH', 'artifacts/dashboard.sqlite3'))
    parser.add_argument('--run-id', default='banksim-local-v1')
    parser.add_argument('--batch-size', type=int, default=25)
    parser.add_argument('--interval', type=float, default=2.0)
    parser.add_argument('--max-batches', type=int, default=None, help='Limiter cette exécution sans perdre la position.')
    args = parser.parse_args()
    if (args.batch_size < 1 or not math.isfinite(args.interval) or args.interval < 0
            or not args.run_id.strip() or (args.max_batches is not None and args.max_batches < 1)):
        parser.error('Paramètres de débit, run-id ou max-batches invalides.')
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        data = load_transactions(args.data)
        scorer = LocalScorer(args.model)
        with Path(args.data).open('rb') as stream:
            data_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        signature = (data_hash + ':'
                     + hashlib.sha256(Path(args.model).read_bytes()).hexdigest() + ':steps>=144:' + FraudInvestigationAgent.version + ':'
                     + os.getenv('FRAUDFLOW_LLM_MODE', 'mock') + ':' + os.getenv('FRAUDFLOW_BEDROCK_MODEL_ID', ''))
        producer = Producer(data, scorer, LocalHistory(args.db), args.run_id, signature)
        batches = 0
        print(json.dumps(dict(event='started', run_id=args.run_id, cursor=producer.cursor, total=len(data))), flush=True)
        while not stop.is_set() and producer.cursor < len(data):
            cursor = producer.tick(args.batch_size)
            batches += 1
            print(json.dumps(dict(event='batch_committed', cursor=cursor, total=len(data))), flush=True)
            if cursor >= len(data) or (args.max_batches and batches >= args.max_batches):
                break
            stop.wait(args.interval)
        print(json.dumps(dict(event='stopped', cursor=producer.cursor, complete=producer.cursor >= len(data))), flush=True)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Producteur interrompu : {error}\n')


if __name__ == '__main__':
    main()
