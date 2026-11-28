"""Lightweight transaction schema shared by model and AWS event handlers."""

NUMERIC = ["step", "amount"]
CATEGORICAL = [
    "customer",
    "age",
    "gender",
    "zipcodeOri",
    "merchant",
    "zipMerchant",
    "category",
]
FEATURES = [*NUMERIC, *CATEGORICAL]
