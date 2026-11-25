import argparse
import json

from fraudflow.dashboard_service import LocalScorer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", required=True, help="Fichier JSON")
    parser.add_argument("--model", default="artifacts/model.joblib")
    args = parser.parse_args()
    with open(args.transaction, encoding="utf-8") as stream:
        transaction = json.load(stream)
    if not isinstance(transaction, dict):
        raise ValueError("Une transaction doit être un objet JSON.")
    result = LocalScorer(args.model).score(transaction)
    output = {key: result[key] for key in ('risk_score', 'threshold', 'alert')}
    if 'investigation' in result:
        output['investigation'] = result['investigation']
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
