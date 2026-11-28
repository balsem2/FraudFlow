"""Replay BankSim transactions to the configured Kinesis stream."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import time

from fraudflow.replay import load_transactions


def publish(data, stream_name, run_id, client, batch_size=100, max_attempts=5):
    if batch_size < 1 or batch_size > 500:
        raise ValueError("batch_size must be between 1 and 500")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    rows = data.to_dict("records")
    for offset in range(0, len(rows), batch_size):
        entries = []
        for position, transaction in enumerate(rows[offset:offset + batch_size], offset):
            clean = {
                key: value.item() if hasattr(value, "item") else value
                for key, value in transaction.items()
                if key not in {"fraud", "_investigation_context", "investigation_cause"}
            }
            customer = str(clean.get("customer", "unknown"))
            partition_key = hashlib.sha256(customer.encode("utf-8")).hexdigest()
            clean["transaction_id"] = f"{run_id}:{position}"
            clean["timestamp"] = datetime.now(timezone.utc).isoformat()
            clean["schema_version"] = 1
            entries.append({
                "Data": json.dumps(clean, separators=(",", ":"), allow_nan=False),
                "PartitionKey": partition_key,
            })

        remaining = entries
        for attempt in range(max_attempts):
            response = client.put_records(StreamName=stream_name, Records=remaining)
            failures = response.get("FailedRecordCount", 0)
            if failures == 0:
                break
            remaining = [
                entry for entry, result in zip(remaining, response["Records"])
                if result.get("ErrorCode")
            ]
            if attempt + 1 == max_attempts:
                raise RuntimeError(
                    f"Kinesis did not accept {len(remaining)} records after {max_attempts} attempts"
                )
            time.sleep(min(2 ** attempt, 8))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=os.getenv("FRAUDFLOW_DATA_PATH", "data/banksim.csv"))
    parser.add_argument("--stream", default=os.getenv("FRAUDFLOW_KINESIS_STREAM"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))
    args = parser.parse_args()
    if not args.stream:
        parser.error("--stream or FRAUDFLOW_KINESIS_STREAM is required")
    if not args.region:
        parser.error("--region or AWS_REGION is required")

    import boto3

    data = load_transactions(args.data)
    client = boto3.client("kinesis", region_name=args.region)
    publish(data, args.stream, args.run_id, client)
    print(f"Published {len(data)} transactions to {args.stream} with run-id {args.run_id}.")


if __name__ == "__main__":
    main()
