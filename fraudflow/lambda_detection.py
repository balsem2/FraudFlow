"""Kinesis-triggered scoring, persistence, and alert publication."""
from datetime import datetime, timezone
from decimal import Decimal
import base64
import hashlib
import json
import logging
import math
import os

from fraudflow.contract import FEATURES

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "investigation-v3"


def _clients():
    import boto3

    return (
        boto3.client("sagemaker-runtime"),
        boto3.resource("dynamodb").Table(os.environ["FRAUDFLOW_TABLE_NAME"]),
        boto3.client("sqs"),
    )


def _decimal_values(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _decimal_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_values(item) for item in value]
    return value


def _hash_identifier(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _timestamp(value):
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("timestamp must be an ISO-8601 datetime") from error
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_transaction(transaction):
    if not isinstance(transaction, dict):
        raise ValueError("event must be a JSON object")
    if "fraud" in transaction:
        raise ValueError("training label is not accepted")
    missing = set(FEATURES) - set(transaction)
    if missing:
        raise ValueError("event is missing required transaction features")
    transaction_id = transaction.get("transaction_id")
    if not isinstance(transaction_id, str) or not transaction_id.strip():
        raise ValueError("transaction_id is required")
    for field in ("step", "amount"):
        value = transaction[field]
        if isinstance(value, bool):
            raise ValueError(f"{field} must be a non-negative finite number")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field} must be a non-negative finite number") from error
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"{field} must be a non-negative finite number")
    for field in set(FEATURES) - {"step", "amount"}:
        if transaction[field] is None or not str(transaction[field]).strip():
            raise ValueError(f"{field} must not be empty")
    return transaction


def _build_item(transaction, prediction, created_at):
    customer_hash = _hash_identifier(transaction["customer"])
    merchant_hash = _hash_identifier(transaction["merchant"])
    item = {
        "transaction_id": transaction["transaction_id"],
        "record_type": "transaction",
        "customer_hash": customer_hash,
        "created_at": created_at,
        "customer": customer_hash,
        "merchant": merchant_hash,
        "step": _decimal_values(transaction["step"]),
        "amount": _decimal_values(transaction["amount"]),
        "category": str(transaction["category"]),
        "risk_score": _decimal_values(prediction["risk_score"]),
        "threshold": _decimal_values(prediction["threshold"]),
        "alert": bool(prediction["alert"]),
        "model_version": str(prediction["model_version"]),
        "investigation_status": "pending" if prediction["alert"] else "not_required",
    }
    return item


def _publish_alert(queue, item):
    deduplication_id = hashlib.sha256(
        f"{item['transaction_id']}:{item['model_version']}:{AGENT_VERSION}".encode("utf-8")
    ).hexdigest()
    queue.send_message(
        QueueUrl=os.environ["FRAUDFLOW_ALERT_QUEUE_URL"],
        MessageBody=json.dumps({"transaction_id": item["transaction_id"]}),
        MessageGroupId=item["customer_hash"],
        MessageDeduplicationId=deduplication_id,
    )


def _process_transaction(transaction, runtime, table, queue):
    transaction = _validate_transaction(transaction)
    created_at = _timestamp(transaction.get("timestamp"))
    request = {key: transaction[key] for key in FEATURES}
    request["transaction_id"] = transaction["transaction_id"]
    response = runtime.invoke_endpoint(
        EndpointName=os.environ["FRAUDFLOW_SAGEMAKER_ENDPOINT"],
        ContentType="application/json",
        Body=json.dumps(request, separators=(",", ":"), default=str),
    )
    prediction = json.loads(response["Body"].read())
    if (prediction.get("transaction_id") != transaction["transaction_id"]
            or not isinstance(prediction.get("alert"), bool)
            or not isinstance(prediction.get("model_version"), str)):
        raise RuntimeError("SageMaker returned an invalid prediction contract")
    try:
        risk = float(prediction["risk_score"])
        threshold = float(prediction["threshold"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("SageMaker returned invalid score fields") from error
    if not math.isfinite(risk) or not 0 <= risk <= 1 or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise RuntimeError("SageMaker returned out-of-range score fields")
    if prediction["alert"] != (risk >= threshold):
        raise RuntimeError("SageMaker alert does not match the saved threshold")

    item = _build_item(transaction, prediction, created_at)
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(transaction_id)")
    except Exception as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing = table.get_item(
            Key={"transaction_id": transaction["transaction_id"]},
            ConsistentRead=True,
        ).get("Item")
        if not existing:
            raise
        item = existing

    if item.get("alert") and item.get("investigation_status") == "pending":
        _publish_alert(queue, item)


def handler(event, context):
    runtime, table, queue = _clients()
    failures = []
    for record in event.get("Records", []):
        try:
            payload = base64.b64decode(record["kinesis"]["data"], validate=True)
            transaction = json.loads(payload)
            _process_transaction(transaction, runtime, table, queue)
        except Exception as error:
            LOGGER.error("Detection record failed (%s)", type(error).__name__)
            failures.append({"itemIdentifier": record.get("eventID", "")})
    return {"batchItemFailures": failures}
