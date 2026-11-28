"""AWS scoring and history adapters used only when FRAUDFLOW_BACKEND=aws."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from uuid import uuid4

import pandas as pd

from fraudflow.model import features


def _decimalize(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _decimalize(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_decimalize(item) for item in value]
    return value


def _python_values(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _python_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_python_values(item) for item in value]
    return value


def _hash_identifier(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


class SageMakerScorer:
    def __init__(self, endpoint_name=None, region=None, client=None):
        self.endpoint_name = endpoint_name or os.environ["FRAUDFLOW_SAGEMAKER_ENDPOINT"]
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        self.client = client
        self.version = self.endpoint_name
        self.threshold = None

    def _client(self):
        if self.client is None:
            import boto3

            self.client = boto3.client("sagemaker-runtime", region_name=self.region)
        return self.client

    def score(self, transaction, context=None):
        clean = features(pd.DataFrame([transaction]))
        transaction_id = transaction.get("transaction_id") or str(uuid4())
        payload = clean.iloc[0].to_dict()
        payload["transaction_id"] = transaction_id
        response = self._client().invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps(payload, separators=(",", ":"), default=str),
        )
        prediction = json.loads(response["Body"].read())
        if not isinstance(prediction, dict) or prediction.get("transaction_id") != transaction_id:
            raise RuntimeError("SageMaker response transaction_id did not match the request.")
        if not isinstance(prediction.get("alert"), bool) or not isinstance(prediction.get("model_version"), str):
            raise RuntimeError("SageMaker response did not match the prediction contract.")
        try:
            risk_score = float(prediction["risk_score"])
            threshold = float(prediction["threshold"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("SageMaker response contained invalid score fields.") from error
        if (not math.isfinite(risk_score) or not 0 <= risk_score <= 1
                or not math.isfinite(threshold) or not 0 <= threshold <= 1):
            raise RuntimeError("SageMaker response scores must be between zero and one.")
        if prediction["alert"] != (risk_score >= threshold):
            raise RuntimeError("SageMaker alert does not match the saved threshold.")
        return {
            "id": transaction_id,
            "transaction_id": transaction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **clean.iloc[0].to_dict(),
            "risk_score": risk_score,
            "threshold": threshold,
            "alert": prediction["alert"],
            "model_version": str(prediction["model_version"]),
            "investigation_status": "pending" if prediction["alert"] else "not_required",
        }

    def score_with_history(self, transaction, history):
        return self.score(transaction)


class DynamoHistory:
    def __init__(self, table_name=None, queue_url=None, region=None, table=None, sqs=None):
        self.table_name = table_name or os.environ["FRAUDFLOW_TABLE_NAME"]
        self.queue_url = queue_url or os.environ["FRAUDFLOW_ALERT_QUEUE_URL"]
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        self._table = table
        self._sqs = sqs

    @property
    def table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=self.region).Table(self.table_name)
        return self._table

    @property
    def sqs(self):
        if self._sqs is None:
            import boto3

            self._sqs = boto3.client("sqs", region_name=self.region)
        return self._sqs

    def _item_for(self, record):
        item = {
            key: value for key, value in record.items()
            if key not in {"_investigation_context", "fraud", "investigation_cause"}
        }
        item["transaction_id"] = str(record.get("transaction_id") or record["id"])
        item["record_type"] = "transaction"
        item["customer_hash"] = _hash_identifier(record["customer"])
        item["customer"] = item["customer_hash"]
        item["merchant"] = _hash_identifier(record["merchant"])
        item["zipMerchant"] = _hash_identifier(record["zipMerchant"])
        item["zipcodeOri"] = _hash_identifier(record["zipcodeOri"])
        return _decimalize(item)

    def add(self, record):
        item = self._item_for(record)
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(transaction_id)",
            )
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            item = self.table.get_item(
                Key={"transaction_id": item["transaction_id"]},
                ConsistentRead=True,
            ).get("Item")
            if not item:
                raise
        if item.get("alert") and item.get("investigation_status") == "pending":
            digest = hashlib.sha256(
                f"{item['transaction_id']}:{item['model_version']}:investigation-v3".encode("utf-8")
            ).hexdigest()
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps({"transaction_id": item["transaction_id"]}),
                MessageGroupId=item["customer_hash"],
                MessageDeduplicationId=digest,
            )

    def add_batch(self, records):
        for record in records:
            self.add(record)

    def recent(self, limit=1000):
        from boto3.dynamodb.conditions import Key

        response = self.table.query(
            IndexName=os.getenv("FRAUDFLOW_RECENT_INDEX", "recent-index"),
            KeyConditionExpression=Key("record_type").eq("transaction"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_python_values(item) for item in response.get("Items", [])]

    def context_for(self, transaction):
        from boto3.dynamodb.conditions import Key

        customer_hash = _hash_identifier(transaction["customer"])
        timestamp = transaction.get("created_at") or datetime.now(timezone.utc).isoformat()
        response = self.table.query(
            IndexName=os.getenv("FRAUDFLOW_CUSTOMER_INDEX", "customer-history-index"),
            KeyConditionExpression=(
                Key("customer_hash").eq(customer_hash) & Key("created_at").lt(timestamp)
            ),
            ScanIndexForward=False,
            Limit=100,
        )
        return {"history": [_python_values(item) for item in response.get("Items", [])]}
