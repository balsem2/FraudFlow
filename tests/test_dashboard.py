import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier
from streamlit.testing.v1 import AppTest

from fraudflow.dashboard_service import LocalHistory
from fraudflow.model import features, pipeline
from fraudflow.replay import load_transactions, replay_batch

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_submission_persistence_filter_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as temp:
            model_path = Path(temp) / 'model.joblib'
            db_path = Path(temp) / 'history.sqlite3'
            row = dict(step=0, amount=1, customer='C1', merchant='M1', age='3',
                       gender='F', zipcodeOri='28007', zipMerchant='28007', category='es_transportation')
            model = pipeline()
            model.set_params(model=DummyClassifier(strategy='constant', constant=1))
            model.fit(features(pd.DataFrame([row, dict(row, amount=100)])), [0, 1])
            joblib.dump({'pipeline': model, 'threshold': 0.5}, model_path)
            with patch.dict(os.environ, FRAUDFLOW_MODEL_PATH=str(model_path), FRAUDFLOW_DB_PATH=str(db_path)):
                app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
                self.assertFalse(app.exception)
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(LocalHistory(db_path).recent()), 1)
                self.assertTrue(LocalHistory(db_path).recent()[0]['alert'])
                app.checkbox(key='alerts_only').check().run()
                self.assertEqual(len(app.dataframe[0].value), 1)
                app.text_input(key='customer').set_value(' ')
                app.button[0].click().run()
                self.assertTrue(app.error)
                self.assertEqual(len(LocalHistory(db_path).recent()), 1)
                reloaded = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
                self.assertFalse(reloaded.exception)
                self.assertEqual(len(reloaded.dataframe[0].value), 1)
                app.session_state['replay_data'] = pd.DataFrame([dict(row, step=144), dict(row, step=145)])
                app.session_state['replay_run'] = 'ui-test'
                app.button(key='replay_start').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state['replay_cursor'], 2)
                self.assertFalse(app.session_state['replay_running'])
                self.assertEqual(len(LocalHistory(db_path).recent()), 3)

    def test_missing_model_is_explained(self):
        with patch.dict(os.environ, FRAUDFLOW_MODEL_PATH=str(ROOT / 'artifacts/nonexistent.joblib')):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)

    def test_replay_order_retry_and_end(self):
        class Scorer:
            def score(self, row):
                self.no_label = 'fraud' not in row
                return dict(row, id='temporary', risk_score=0.1, alert=False)

        with tempfile.TemporaryDirectory() as temp:
            row = dict(amount=10, customer='C1', merchant='M1', age='3', gender='F',
                       zipcodeOri='28007', zipMerchant='28007', category='es_food', fraud=1)
            path = Path(temp) / 'data.csv'
            pd.DataFrame([dict(row, step=145), dict(row, step=0), dict(row, step=144)]).to_csv(path, index=False)
            data = load_transactions(path)
            self.assertEqual(data.step.tolist(), [144, 145])
            self.assertNotIn('fraud', data)
            store = LocalHistory(Path(temp) / 'db.sqlite3')
            scorer = Scorer()
            self.assertEqual(replay_batch(data, 0, 1, 'run', scorer, store), 1)
            replay_batch(data, 0, 1, 'run', scorer, store)
            self.assertEqual(len(store.recent()), 1)
            self.assertEqual(replay_batch(data, 1, 50, 'run', scorer, store), 2)
            self.assertEqual(replay_batch(data, 2, 50, 'run', scorer, store), 2)
            self.assertEqual(len(store.recent()), 2)
            self.assertTrue(scorer.no_label)
