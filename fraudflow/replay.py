"""Chronological replay, independent of the Streamlit interface."""
import pandas as pd
from fraudflow.model import FEATURES, features


def load_transactions(path):
    data = pd.read_csv(path, usecols=FEATURES)
    data = features(data)
    # Same recent period as the established BankSim test; simulation, not new evaluation.
    return data.loc[data.step >= 144].sort_values('step', kind='stable').reset_index(drop=True)


def replay_batch(data, cursor, size, run_id, scorer, history):
    if cursor < 0 or size < 1:
        raise ValueError('Position ou taille de lot invalide.')
    batch = data.iloc[cursor:cursor + size]
    records = []
    for position, transaction in enumerate(batch.to_dict('records'), start=cursor):
        record = scorer.score(transaction)
        record.update(id=f'{run_id}:{position}', source='banksim_replay', replay_run=run_id)
        records.append(record)
    history.add_batch(records)
    return cursor + len(records)
