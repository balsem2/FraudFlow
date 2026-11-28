import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

import joblib

from fraudflow.sagemaker_inference import (
    InvalidTransactionError,
    load_model,
    make_handler,
    predict_transaction,
)


class FixedPipeline:
    def __init__(self, risk_score):
        self.risk_score = risk_score

    def predict_proba(self, frame):
        return [[1 - self.risk_score, self.risk_score]]


class FailingPipeline:
    def predict_proba(self, frame):
        raise ValueError("model failure")


class SageMakerInferenceTests(unittest.TestCase):
    def setUp(self):
        self.transaction = {
            "transaction_id": "tx-1",
            "amount": 12.5,
            "age": "'3'",
            "gender": "'F'",
            "step": 180,
            "customer": "customer-1",
            "merchant": "merchant-1",
            "zipcodeOri": "28007",
            "zipMerchant": "28007",
            "category": "'es_transportation'",
        }
        self.model = {
            "pipeline": FixedPipeline(0.9),
            "threshold": 0.5,
            "version": "test-version",
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.model))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        if isinstance(body, dict):
            body = json.dumps(body)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_load_model_records_file_hash_and_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            joblib.dump({"pipeline": FixedPipeline(0.9), "threshold": 0.5}, path)

            loaded = load_model(directory)

            self.assertEqual(loaded["version"], hashlib.sha256(path.read_bytes()).hexdigest()[:12])
            self.assertEqual(loaded["threshold"], 0.5)

    def test_prediction_uses_threshold_and_preserves_transaction_id(self):
        result = predict_transaction(self.transaction, self.model)

        self.assertEqual(result["risk_score"], 0.9)
        self.assertTrue(result["alert"])
        self.assertEqual(result["transaction_id"], "tx-1")
        self.assertEqual(result["model_version"], "test-version")

    def test_prediction_rejects_label_and_missing_features(self):
        with self.assertRaises(InvalidTransactionError):
            predict_transaction(dict(self.transaction, fraud=0), self.model)
        with self.assertRaises(InvalidTransactionError):
            predict_transaction({"amount": 1}, self.model)

    def test_ping_and_invocations_http_contract(self):
        status, health = self.request("GET", "/ping")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok"})

        status, health = self.request("POST", "/ping")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok"})

        status, result = self.request(
            "POST",
            "/invocations",
            self.transaction,
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["risk_score"], 0.9)
        self.assertTrue(result["alert"])

    def test_http_rejects_label_and_invalid_content_type(self):
        status, error = self.request(
            "POST",
            "/invocations",
            dict(self.transaction, fraud=0),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(error["error"], "Invalid transaction payload")

        status, error = self.request("POST", "/invocations", "{}", {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertIn("Content-Type", error["error"])

    def test_http_rejects_malformed_json(self):
        status, error = self.request(
            "POST",
            "/invocations",
            "{",
            {"Content-Type": "application/json"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(error["error"], "Request body must be valid JSON")

    def test_model_failure_returns_server_error(self):
        self.model["pipeline"] = FailingPipeline()

        status, error = self.request(
            "POST",
            "/invocations",
            self.transaction,
            {"Content-Type": "application/json"},
        )

        self.assertEqual(status, 500)
        self.assertEqual(error["error"], "Inference failed")


if __name__ == "__main__":
    unittest.main()
