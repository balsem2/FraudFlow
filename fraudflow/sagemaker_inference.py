"""HTTP inference entry point compatible with SageMaker real-time endpoints."""
import argparse
import hashlib
import json
import logging
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import joblib
import pandas as pd

from fraudflow.model import features

LOGGER = logging.getLogger(__name__)
MODEL_FILENAME = "model.joblib"
MAX_REQUEST_BYTES = 25_000_000


class InvalidTransactionError(ValueError):
    pass


def load_model(model_dir):
    model_path = Path(model_dir) / MODEL_FILENAME
    if not model_path.is_file():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")

    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict) or "pipeline" not in artifact or "threshold" not in artifact:
        raise ValueError("Model artifact must contain a pipeline and threshold.")

    pipeline = artifact["pipeline"]
    if not callable(getattr(pipeline, "predict_proba", None)):
        raise ValueError("Model pipeline must provide predict_proba.")
    threshold = float(artifact["threshold"])
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Model threshold must be between zero and one.")

    version = hashlib.sha256(model_path.read_bytes()).hexdigest()[:12]
    return {"pipeline": pipeline, "threshold": threshold, "version": version}


def predict_transaction(transaction, model):
    if not isinstance(transaction, dict):
        raise InvalidTransactionError("Transaction must be a JSON object.")
    if "fraud" in transaction:
        raise InvalidTransactionError("The fraud training label is not accepted for inference.")

    transaction_id = transaction.get("transaction_id")
    if transaction_id is not None and not isinstance(transaction_id, str):
        raise InvalidTransactionError("transaction_id must be a string.")

    try:
        clean = features(pd.DataFrame([transaction]))
    except (TypeError, ValueError):
        raise InvalidTransactionError("Invalid transaction features.") from None
    probabilities = model["pipeline"].predict_proba(clean)
    if len(probabilities) != 1 or len(probabilities[0]) < 2:
        raise RuntimeError("Model returned an invalid probability result.")
    risk_score = float(probabilities[0][1])
    if not math.isfinite(risk_score) or not 0 <= risk_score <= 1:
        raise RuntimeError("Model returned an invalid probability.")

    result = {
        "risk_score": risk_score,
        "threshold": model["threshold"],
        "alert": risk_score >= model["threshold"],
        "model_version": model["version"],
    }
    if transaction_id is not None:
        result["transaction_id"] = transaction_id
    return result


def make_handler(model):
    class InferenceRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "FraudFlowInference/1.0"

        def _send_json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _path(self):
            return urlsplit(self.path).path

        def do_GET(self):
            if self._path() == "/ping":
                self._send_json(200, {"status": "ok"})
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self):
            path = self._path()
            if path == "/ping":
                self.close_connection = True
                self._send_json(200, {"status": "ok"})
                return
            if path != "/invocations":
                self.close_connection = True
                self._send_json(404, {"error": "Not found"})
                return

            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self.close_connection = True
                self._send_json(415, {"error": "Content-Type must be application/json"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self.close_connection = True
                self._send_json(400, {"error": "A valid Content-Length is required"})
                return
            if content_length < 0:
                self.close_connection = True
                self._send_json(400, {"error": "A valid Content-Length is required"})
                return
            if content_length > MAX_REQUEST_BYTES:
                self.close_connection = True
                self._send_json(413, {"error": "Request body is too large"})
                return

            try:
                transaction = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.close_connection = True
                self._send_json(400, {"error": "Request body must be valid JSON"})
                return

            try:
                result = predict_transaction(transaction, model)
            except InvalidTransactionError:
                self.close_connection = True
                self._send_json(400, {"error": "Invalid transaction payload"})
                return
            except Exception as error:
                LOGGER.error("Inference failed with %s", type(error).__name__)
                self.close_connection = True
                self._send_json(500, {"error": "Inference failed"})
                return
            self._send_json(200, result)

        def log_message(self, format_string, *args):
            LOGGER.info("%s - %s", self.address_string(), format_string % args)

    return InferenceRequestHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("serve",), default="serve")
    args = parser.parse_args()
    if args.command != "serve":
        parser.error("Only the serve command is supported.")

    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        parser.error("PORT must be between 1 and 65535.")

    model_dir = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
    model = load_model(model_dir)
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(model))
    LOGGER.info("Inference server listening on port %d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Inference server stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
