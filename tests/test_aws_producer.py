import json
import unittest

import pandas as pd

from fraudflow.aws_producer import publish


class PartialFailureKinesis:
    def __init__(self):
        self.calls = []

    def put_records(self, **request):
        self.calls.append(request["Records"])
        if len(self.calls) == 1:
            return {
                "FailedRecordCount": 1,
                "Records": [
                    {"SequenceNumber": "1"},
                    {"ErrorCode": "ProvisionedThroughputExceededException"},
                ],
            }
        return {
            "FailedRecordCount": 0,
            "Records": [{"SequenceNumber": "2"}],
        }


class AwsProducerTests(unittest.TestCase):
    def test_retries_only_failed_records_without_label(self):
        transactions = pd.DataFrame([
            {
                "step": 1,
                "amount": 10.0,
                "customer": "customer-1",
                "age": "3",
                "gender": "F",
                "zipcodeOri": "28007",
                "merchant": "merchant-1",
                "zipMerchant": "28007",
                "category": "es_food",
                "fraud": 1,
            },
            {
                "step": 2,
                "amount": 20.0,
                "customer": "customer-2",
                "age": "2",
                "gender": "M",
                "zipcodeOri": "28007",
                "merchant": "merchant-2",
                "zipMerchant": "28007",
                "category": "es_food",
                "fraud": 0,
            },
        ])
        client = PartialFailureKinesis()

        publish(transactions, "transactions", "run-1", client, batch_size=2)

        first = [json.loads(entry["Data"]) for entry in client.calls[0]]
        retried = [json.loads(entry["Data"]) for entry in client.calls[1]]
        self.assertEqual([row["transaction_id"] for row in first], ["run-1:0", "run-1:1"])
        self.assertEqual(len(retried), 1)
        self.assertEqual(retried[0]["transaction_id"], "run-1:1")
        self.assertTrue(all("fraud" not in row for row in first))


if __name__ == "__main__":
    unittest.main()
