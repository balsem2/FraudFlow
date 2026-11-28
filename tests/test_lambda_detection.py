import base64
import io
import json
import unittest
from unittest.mock import patch

from fraudflow.lambda_detection import handler


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke_endpoint(self, **request):
        self.calls.append(request)
        transaction = json.loads(request["Body"])
        prediction = {
            "transaction_id": transaction["transaction_id"],
            "risk_score": 0.9,
            "threshold": 0.34,
            "alert": True,
            "model_version": "model-v1",
        }
        return {"Body": io.BytesIO(json.dumps(prediction).encode("utf-8"))}


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, **request):
        self.items.append(request["Item"])


class FakeQueue:
    def __init__(self):
        self.messages = []

    def send_message(self, **message):
        self.messages.append(message)


class DetectionLambdaTests(unittest.TestCase):
    def transaction(self):
        return {
            "transaction_id": "tx-1",
            "step": 180,
            "amount": 12.5,
            "customer": "customer-1",
            "age": "3",
            "gender": "F",
            "zipcodeOri": "28007",
            "merchant": "merchant-1",
            "zipMerchant": "28007",
            "category": "es_transportation",
        }

    def test_handler_scores_persists_and_publishes_only_transaction_id(self):
        runtime = FakeRuntime()
        table = FakeTable()
        queue = FakeQueue()
        record = self.transaction()
        event = {
            "Records": [{
                "eventID": "shardId-000:1",
                "kinesis": {
                    "data": base64.b64encode(json.dumps(record).encode("utf-8")).decode("ascii"),
                },
            }],
        }

        environment = {
            "FRAUDFLOW_TABLE_NAME": "transactions",
            "FRAUDFLOW_SAGEMAKER_ENDPOINT": "endpoint",
            "FRAUDFLOW_ALERT_QUEUE_URL": "queue-url",
        }
        with patch.dict("os.environ", environment), patch(
            "fraudflow.lambda_detection._clients", return_value=(runtime, table, queue)
        ):
            result = handler(event, None)

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertTrue(table.items[0]["alert"])
        self.assertNotEqual(table.items[0]["customer"], record["customer"])
        self.assertEqual(len(queue.messages), 1)
        self.assertEqual(json.loads(queue.messages[0]["MessageBody"]), {"transaction_id": "tx-1"})

    def test_handler_rejects_training_label_with_partial_failure(self):
        runtime = FakeRuntime()
        table = FakeTable()
        queue = FakeQueue()
        record = dict(self.transaction(), fraud=1)
        event = {
            "Records": [{
                "eventID": "shardId-000:2",
                "kinesis": {
                    "data": base64.b64encode(json.dumps(record).encode("utf-8")).decode("ascii"),
                },
            }],
        }

        environment = {
            "FRAUDFLOW_TABLE_NAME": "transactions",
            "FRAUDFLOW_SAGEMAKER_ENDPOINT": "endpoint",
            "FRAUDFLOW_ALERT_QUEUE_URL": "queue-url",
        }
        with patch.dict("os.environ", environment), patch(
            "fraudflow.lambda_detection._clients", return_value=(runtime, table, queue)
        ):
            result = handler(event, None)

        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "shardId-000:2"}]})
        self.assertEqual(runtime.calls, [])
        self.assertEqual(table.items, [])


if __name__ == "__main__":
    unittest.main()
