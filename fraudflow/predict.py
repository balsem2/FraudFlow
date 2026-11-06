import argparse
import json

import joblib
import pandas as pd

from fraudflow.model import features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", required=True, help="Fichier JSON")
    parser.add_argument("--model", default="artifacts/model.joblib")
    args = parser.parse_args()
    with open(args.transaction, encoding="utf-8") as stream:
        transaction = json.load(stream)
    if not isinstance(transaction, dict):
        raise ValueError("Une transaction doit être un objet JSON.")
    x = features(pd.DataFrame([transaction]))
    # Load only artifacts produced locally or from a trusted source.
    artifact = joblib.load(args.model)
    score = float(artifact["pipeline"].predict_proba(x)[0, 1])
    print(json.dumps({"risk_score": score, "threshold": artifact["threshold"],
                      "alert": score >= artifact["threshold"]}, indent=2))


if __name__ == "__main__":
    main()
