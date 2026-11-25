"""Chronological replay, independent of the Streamlit interface."""
import pandas as pd
from fraudflow.model import FEATURES, features


def load_transactions(path):
    from pathlib import Path
    if Path(path).suffix == '.jsonl':
        from fraudflow.synthetic_investigation import load_events
        events = load_events(path)
        # Labels, supplied indicators and scenario names are deliberately not forwarded.
        data = features(pd.DataFrame([event['transaction'] for event in events]))
        data['transaction_id'] = [event['transaction'].get('transaction_id', event.get('transaction_id')) for event in events]
        data['_investigation_context'] = [event['context'] for event in events]
        return data.sort_values('step', kind='stable').reset_index(drop=True)
    from fraudflow.synthetic_investigation import identified_transactions
    data, _ = identified_transactions(path)
    # Same recent period as the established BankSim test; simulation, not new evaluation.
    return data.loc[data.step >= 144].sort_values('step', kind='stable').reset_index(drop=True)


def replay_batch(data, cursor, size, run_id, scorer, history):
    if cursor < 0 or size < 1:
        raise ValueError('Position ou taille de lot invalide.')
    batch = data.iloc[cursor:cursor + size]
    records = []
    for position, transaction in enumerate(batch.to_dict('records'), start=cursor):
        record = (scorer.score_with_history(transaction, history) if hasattr(scorer, 'score_with_history')
                  else scorer.score(transaction))
        record.update(id=f'{run_id}:{position}', source='banksim_replay', replay_run=run_id)
        records.append(record)
    history.add_batch(records)
    return cursor + len(records)
