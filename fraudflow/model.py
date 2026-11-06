import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier

CATEGORICAL = ["customer", "age", "gender", "zipcodeOri", "merchant", "zipMerchant", "category"]
NUMERIC = ["step", "amount"]
FEATURES = [*NUMERIC, *CATEGORICAL]


def features(frame):
    missing = set(FEATURES) - set(frame.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes: {sorted(missing)}")
    result = frame[FEATURES].copy()
    if result.empty or result.isna().any().any():
        raise ValueError("Transactions vides ou valeurs manquantes.")
    for column in NUMERIC:
        result[column] = pd.to_numeric(result[column], errors="raise")
        if not np.isfinite(result[column]).all() or (result[column] < 0).any():
            raise ValueError(f"Valeur numérique invalide: {column}")
    if (result["step"] % 1 != 0).any():
        raise ValueError("step doit être entier.")
    if not np.isfinite(result["amount"]).all() or (result["amount"] < 0).any():
        raise ValueError("Le montant doit être fini et positif ou nul.")
    for column in CATEGORICAL:
        result[column] = result[column].astype(str).str.strip().str.strip("'")
        if result[column].eq("").any():
            raise ValueError(f"Catégorie vide: {column}")
    return result


def pipeline():
    return Pipeline([
        ("encoding", ColumnTransformer([
            ("category", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("numeric", "passthrough", NUMERIC),
        ])),
        ("model", XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.08,
            tree_method="hist", eval_metric="logloss", random_state=42,
            n_jobs=2,
        )),
    ])
