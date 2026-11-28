import hashlib
import io
import json
import unittest

from fraudflow.aws_adapters import DynamoHistory, SageMakerScorer


class FakeRuntime:
    def __init__(self, prediction):
        self.prediction = prediction
        self.request = None

    def invoke_endpoint(self, **request):
        self.request = request
        return {"Body": io.BytesIO(json.dumps(self.prediction).encode("utf-8"))}


class FakeTable:
    def __init__(self):
        self.item = None

    def put_item(self, **kwargs):
        self.item = kwargs["Item"]


class FakeQueue:
    def __init__(self):
        self.messages = []

    def send_message(self, **message):
        self.messages.append(message)


class AwsAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transaction = {
            "transaction_id": "tx-1",
            "step": 180,
            "amount": 12.5,
            "customer": "customer-1",
            "age": "'3'",
            "gender": "'F'",
            "zipcodeOri": "28007",
            "merchant": "merchant-1",
            "zipMerchant": "28007",
            "category": "'es_transportation'",
        }

    def test_sagemaker_scorer_uses_the_served_threshold_and_contract(self):
        runtime = FakeRuntime({
            "transaction_id": "tx-1",
            "risk_score": 0.8,
            "threshold": 0.34,
            "alert": True,
            "model_version": "model-v1",
        })

        record = SageMakerScorer("endpoint", client=runtime).score(self.transaction)

        self.assertTrue(record["alert"])
        self.assertEqual(record["risk_score"], 0.8)
        self.assertEqual(record["threshold"], 0.34)
        self.assertEqual(runtime.request["EndpointName"], "endpoint")
        self.assertEqual(json.loads(runtime.request["Body"])["transaction_id"], "tx-1")

    def test_sagemaker_scorer_rejects_inconsistent_prediction(self):
        runtime = FakeRuntime({
            "transaction_id": "tx-1",
            "risk_score": 0.2,
            "threshold": 0.34,
            "alert": True,
            "model_version": "model-v1",
        })

        with self.assertRaisesRegex(RuntimeError, "saved threshold"):
            SageMakerScorer("endpoint", client=runtime).score(self.transaction)

    def test_dynamo_history_hashes_identifiers_and_queues_alert(self):
        table = FakeTable()
        queue = FakeQueue()
        history = DynamoHistory(
            table_name="transactions",
            queue_url="queue-url",
            table=table,
            sqs=queue,
        )
        record = {
            **self.transaction,
            "id": "tx-1",
            "created_at": "2026-01-01T00:00:00Z",
            "risk_score": 0.8,
            "threshold": 0.34,
            "alert": True,
            "model_version": "model-v1",
            "investigation_status": "pending",
            "fraud": 1,
        }

        history.add(record)

        expected_customer = hashlib.sha256(b"customer-1").hexdigest()
        self.assertEqual(table.item["customer_hash"], expected_customer)
        self.assertEqual(table.item["customer"], expected_customer)
        self.assertNotIn("fraud", table.item)
        self.assertEqual(len(queue.messages), 1)
        self.assertEqual(json.loads(queue.messages[0]["MessageBody"]), {"transaction_id": "tx-1"})


if __name__ == "__main__":
    unittest.main()
