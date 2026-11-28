"""SQS-triggered, alert-only Bedrock investigation handler."""
from datetime import datetime, timezone
import json
import logging
import os
import time

from fraudflow.investigation import BedrockLLM, FraudInvestigationAgent

LOGGER = logging.getLogger(__name__)


def _clients():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["FRAUDFLOW_TABLE_NAME"])


def _investigate(table, transaction_id):
    from boto3.dynamodb.conditions import Key

    response = table.get_item(Key={"transaction_id": transaction_id}, ConsistentRead=True)
    item = response.get("Item")
    if not item or not item.get("alert"):
        raise ValueError("Investigation event has no matching alert")
    if item.get("investigation_status") == "completed":
        return

    table.update_item(
        Key={"transaction_id": transaction_id},
        UpdateExpression="SET investigation_status = :processing",
        ConditionExpression="investigation_status IN (:pending, :degraded, :processing)",
        ExpressionAttributeValues={
            ":processing": "processing",
            ":pending": "pending",
            ":degraded": "degraded",
        },
    )
    try:
        prior = table.query(
            IndexName=os.environ["FRAUDFLOW_CUSTOMER_INDEX"],
            KeyConditionExpression=(
                Key("customer_hash").eq(item["customer_hash"])
                & Key("created_at").lt(item["created_at"])
            ),
            ScanIndexForward=False,
            Limit=100,
        ).get("Items", [])
        context = {
            "timestamp": item["created_at"],
            "timestamp_source": "observed",
            "history": [
                {
                    "customer": row["customer"],
                    "merchant": row["merchant"],
                    "category": row["category"],
                    "step": row["step"],
                    "amount": row["amount"],
                    "risk_score": row["risk_score"],
                    "timestamp": row["created_at"],
                }
                for row in prior
            ],
        }
        transaction = {
            "customer": item["customer"],
            "merchant": item["merchant"],
            "category": item["category"],
            "step": item["step"],
            "amount": item["amount"],
        }
        decision = {
            "alert": True,
            "risk_score": float(item["risk_score"]),
            "threshold": float(item["threshold"]),
        }
        model_id = os.environ["FRAUDFLOW_BEDROCK_MODEL_ID"]
        region = os.environ["FRAUDFLOW_BEDROCK_REGION"]
        investigation = FraudInvestigationAgent(BedrockLLM(model_id, region)).investigate(
            decision, transaction, context
        )
        table.update_item(
            Key={"transaction_id": transaction_id},
            UpdateExpression=(
                "SET investigation = :investigation, investigation_status = :status, "
                "investigated_at = :investigated_at"
            ),
            ExpressionAttributeValues={
                ":investigation": investigation,
                ":status": investigation["status"],
                ":investigated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if investigation["status"] != "completed" or investigation["backend"] != "bedrock":
            raise RuntimeError("Bedrock investigation did not complete successfully")
    except Exception:
        table.update_item(
            Key={"transaction_id": transaction_id},
            UpdateExpression="SET investigation_status = :pending, retry_after = :retry_after",
            ExpressionAttributeValues={
                ":pending": "pending",
                ":retry_after": int(time.time()) + 60,
            },
        )
        raise


def handler(event, context):
    table = _clients()
    failures = []
    records = event.get("Records", [])
    for index, record in enumerate(records):
        try:
            body = json.loads(record["body"])
            transaction_id = body.get("transaction_id")
            if not isinstance(transaction_id, str) or not transaction_id:
                raise ValueError("transaction_id is required")
            _investigate(table, transaction_id)
        except Exception as error:
            LOGGER.error("Investigation message failed (%s)", type(error).__name__)
            failures.extend(
                {"itemIdentifier": failed.get("messageId", "")}
                for failed in records[index:]
            )
            break
    return {"batchItemFailures": failures}
