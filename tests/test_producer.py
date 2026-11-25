from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from fraudflow.dashboard_service import LocalHistory
from fraudflow.producer import Producer


class Scorer:
    def score(self, row):
        return dict(row, id='temporary', risk_score=0.1, alert=False)


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.history = LocalHistory(Path(self.temp.name) / 'history.db')
        self.data = pd.DataFrame({'step': [144, 145, 146], 'amount': [1, 2, 3]})

    def producer(self, signature='same'):
        return Producer(self.data, Scorer(), self.history, 'test', signature)

    def test_resume_and_end_without_duplicates(self):
        self.assertEqual(self.producer().tick(2), 2)
        restarted = self.producer()
        self.assertEqual(restarted.cursor, 2)
        self.assertEqual(restarted.tick(2), 3)
        self.assertEqual(restarted.tick(2), 3)
        self.assertEqual(len(self.history.recent()), 3)

    def test_changed_dataset_or_model_rejected(self):
        self.producer().tick(1)
        with self.assertRaises(ValueError):
            self.producer('changed')

    def test_failed_batch_rolls_back_predictions_and_cursor(self):
        producer = self.producer()
        # Simulate a DB failure on the second record, after the first insert.
        with sqlite3.connect(self.history.path) as db:
            db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON predictions "
                       "WHEN NEW.id='producer:test:1' BEGIN SELECT RAISE(ABORT, 'simulated'); END")
        db.close()
        with self.assertRaises(sqlite3.IntegrityError):
            producer.tick(2)
        self.assertEqual(producer.cursor, 0)
        self.assertEqual(self.history.recent(), [])
