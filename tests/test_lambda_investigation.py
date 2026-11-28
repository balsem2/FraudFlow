import json
import sys
import types
import unittest
from unittest.mock import patch

from fraudflow.lambda_investigation import handler


class FakeBedrock:
    name = "bedrock"

    def __init__(self):
        self.calls = 0

    def generate(self, evidence):
        self.calls += 1
        causes = evidence["candidate_causes"]
        return {
            "causes": causes,
            "confidence": "faible" if not causes else "modérée",
            "explanation": "Aucun indice fort dans l'historique fourni.",
            "action": "manual_review",
        }


class FakeTable:
    def __init__(self):
        self.item = {
            "transaction_id": "tx-1",
            "customer_hash": "hashed-customer",
            "customer": "hashed-customer",
            "merchant": "hashed-merchant",
            "category": "es_food",
            "step": 180,
            "amount": 12.5,
            "created_at": "2026-01-01T00:00:00Z",
            "risk_score": 0.9,
            "threshold": 0.34,
            "alert": True,
            "investigation_status": "pending",
        }
        self.updates = []

    def get_item(self, **request):
        return {"Item": self.item}

    def query(self, **request):
        return {"Items": []}

    def update_item(self, **request):
        self.updates.append(request)
        values = request["ExpressionAttributeValues"]
        if ":processing" in values:
            self.item["investigation_status"] = values[":processing"]
        if ":investigation" in values:
            self.item["investigation"] = values[":investigation"]
            self.item["investigation_status"] = values[":status"]


class FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return self

    def lt(self, value):
        return self

    def __and__(self, other):
        return self


class InvestigationLambdaTests(unittest.TestCase):
    def test_handler_persists_bedrock_investigation_for_alert(self):
        table = FakeTable()
        bedrock = FakeBedrock()
        event = {
            "Records": [{
                "messageId": "message-1",
                "body": json.dumps({"transaction_id": "tx-1"}),
            }],
        }
        environment = {
            "FRAUDFLOW_TABLE_NAME": "transactions",
            "FRAUDFLOW_CUSTOMER_INDEX": "customer-history-index",
            "FRAUDFLOW_BEDROCK_MODEL_ID": "model-id",
            "FRAUDFLOW_BEDROCK_REGION": "eu-north-1",
        }
        conditions = types.ModuleType("boto3.dynamodb.conditions")
        conditions.Key = FakeKey
        dynamodb = types.ModuleType("boto3.dynamodb")
        dynamodb.conditions = conditions
        boto3 = types.ModuleType("boto3")
        boto3.dynamodb = dynamodb

        with patch.dict("os.environ", environment), patch.dict(
            sys.modules,
            {
                "boto3": boto3,
                "boto3.dynamodb": dynamodb,
                "boto3.dynamodb.conditions": conditions,
            },
        ), patch(
            "fraudflow.lambda_investigation._clients", return_value=table
        ), patch("fraudflow.lambda_investigation.BedrockLLM", return_value=bedrock):
            result = handler(event, None)

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(bedrock.calls, 1)
        self.assertEqual(table.item["investigation_status"], "completed")
        self.assertEqual(table.item["investigation"]["backend"], "bedrock")
        self.assertEqual(table.item["investigation"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
