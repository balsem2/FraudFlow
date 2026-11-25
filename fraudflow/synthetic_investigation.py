"""Independent synthetic scenario labels; never a real-world fraud ground truth."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

import pandas as pd
from fraudflow.model import FEATURES, features
from fraudflow.investigation import CAUSES, indicators


def make_context(transaction, causes, rng, index=0):
    # Standalone manual scenario fixture only; NOT used by the linked dataset generator.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(transaction['step']), seconds=index)
    location = 'FR' if 'geographic_anomaly' in causes else 'TN'
    device = 'synthetic-new-device' if 'unknown_device' in causes else 'synthetic-device'
    ip = '203.0.113.10' if 'unknown_ip' in causes else '192.0.2.10'
    if 'account_takeover' in causes:
        device, ip = 'synthetic-new-device', '203.0.113.10'
    baseline = max(float(transaction['amount']), 1) / (rng.uniform(2.5, 6) if 'unusual_amount' in causes else rng.uniform(0.7, 1.7))
    recent = rng.randint(3, 9) if 'high_velocity' in causes else rng.randint(0, 2)
    history = []
    for i in range(12):
        minutes = (i + 1) * 5 if i < recent else (i + 1) * 120
        history.append(dict(customer=transaction['customer'],
                            merchant='synthetic-other-merchant' if 'new_merchant' in causes else transaction['merchant'],
                            category='synthetic-other-category' if 'new_category' in causes else transaction['category'],
                            amount=round(baseline * rng.uniform(0.65, 1.35), 2),
                            timestamp=(now - timedelta(minutes=minutes)).isoformat(),
                            device='synthetic-device', ip='192.0.2.10', country='TN',
                            risk_score=round(rng.betavariate(1, 12), 4)))
    return dict(timestamp=now.isoformat(), synthetic=True, history=history,
                device=device, ip=ip, country=location,
                auth_failures_24h=rng.randint(2, 7) if 'account_takeover' in causes else rng.randint(0, 2))


def identified_transactions(path):
    """IDs bind an immutable source file and its zero-based row (duplicates stay distinct)."""
    import hashlib
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    data = features(pd.read_csv(path, usecols=FEATURES))
    for column in FEATURES:
        if column not in ('step', 'amount'):
            data[column] = data[column].astype('category')
    data['transaction_id'] = [f'banksim-{digest}-{i}' for i in range(len(data))]
    data['source_row'] = range(len(data))
    return data, digest


def generate(path, output, rows=1000, seed=42):
    """BankSim history is observed; only missing security attributes are simulated."""
    import hashlib
    if rows < 1:
        raise ValueError('rows doit ?tre positif.')
    data, digest = identified_transactions(path)
    source_rows = len(data)
    eligible = data.loc[data.step >= 144, 'transaction_id']
    if rows > len(eligible):
        raise ValueError('rows d?passe le nombre de transactions disponibles (sans remplacement).')
    selected = set(eligible.sample(n=rows, random_state=seed))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # An inspectable mapping for EVERY original row, without modifying the source CSV.
    data[['transaction_id', 'source_row']].to_csv(output.parent / 'banksim_transaction_ids.csv', index=False)
    selected_clients = set(data.loc[data.transaction_id.isin(selected), 'customer'])
    data = data.loc[data.customer.isin(selected_clients)]
    history, profiles, summaries = {}, {}, []
    with output.open('w', encoding='utf-8') as stream:
        # Intraday ordering is simulated, reproducible and explicitly marked.
        for step, group in data.groupby('step', sort=True):
            daily = group.to_dict('records')
            for tx in daily:
                clock_rng = random.Random(f'clock:{seed}:{tx["transaction_id"]}')
                tx['timestamp'] = (datetime(2026, 1, 1, tzinfo=timezone.utc) +
                    timedelta(days=int(step), seconds=clock_rng.randrange(86400),
                              microseconds=int(tx['source_row']))).isoformat()
            daily.sort(key=lambda tx: tx['timestamp'])
            for tx in daily:
                customer = tx['customer']
                if customer not in profiles:
                    token = hashlib.sha256(f'{seed}:{customer}'.encode()).hexdigest()[:16]
                    profiles[customer] = dict(device=f'sim-device-{token}-0',
                        ip=f'192.0.2.{int(token[:4],16) % 254 + 1}', country='TN')
                profile = profiles[customer]
                rng = random.Random(f'{seed}:{tx["transaction_id"]}')
                labels = []
                # Changes persist for later transactions of this client.
                if rng.random() < 0.04:
                    profile['device'] = f'sim-device-{tx["source_row"]}'
                    labels.append('unknown_device')
                if rng.random() < 0.06:
                    profile['ip'] = f'203.0.113.{rng.randint(1,254)}'
                    labels.append('unknown_ip')
                if rng.random() < 0.015:
                    profile['country'] = rng.choice(['TN', 'FR', 'DE'])
                    labels.append('geographic_anomaly')
                security = dict(profile, auth_failures_24h=rng.randint(0,6) if rng.random() < 0.06 else 0)
                if rng.random() < 0.02:
                    # Injection label chosen independently of detector rules.
                    # Variable severity deliberately permits missed scenarios.
                    profile['device'] = f'sim-attack-device-{tx["source_row"]}'
                    profile['ip'] = f'203.0.113.{rng.randint(1,254)}'
                    security = dict(profile, auth_failures_24h=rng.randint(1,7))
                    labels.extend(['account_takeover', 'unknown_device', 'unknown_ip'])
                prior = history.get(customer, [])
                if tx['transaction_id'] in selected:
                    transaction = {key: tx[key] for key in FEATURES + ['transaction_id']}
                    context = dict(security, synthetic=True, history=prior,
                        timestamp=tx['timestamp'], timestamp_source='simulated_intraday',
                        history_source='banksim_with_simulated_order', security_source='synthetic',
                        temporal_resolution='simulated_seconds', source_sha256=digest)
                    values = indicators(transaction, context)
                    labels = sorted(set(labels))
                    event = dict(transaction_id=tx['transaction_id'], transaction=transaction,
                        source_row=tx['source_row'], source_sha256=digest,
                        context=context, investigation_cause=labels, synthetic=True,
                        label_source='injected_security_scenario_not_real_fraud',
                        scenario_id=f'linked-{seed}-{tx["source_row"]}')
                    stream.write(json.dumps(event, allow_nan=False) + '\n')
                    summaries.append(dict(transaction_id=tx['transaction_id'], source_row=tx['source_row'],
                        customer=customer, scenario_id=event['scenario_id'], **values,
                        investigation_cause='|'.join(labels), label_source=event['label_source']))
                history.setdefault(customer, []).append(dict(**{k: tx[k] for k in
                    ('transaction_id','customer','step','amount','merchant','category','timestamp')}, **security))
    pd.DataFrame(summaries).to_csv(output.with_suffix('.indicators.csv'), index=False)
    output.with_suffix('.manifest.json').write_text(json.dumps(dict(
        version='linked-history-v3', source_sha256=digest, source_rows=source_rows,
        scenarios=rows, seed=seed, sampling='without_replacement',
        history='same customer, strictly earlier simulated timestamps; BankSim days preserved',
        simulated_fields=['timestamp','device','ip','country','auth_failures_24h'],
        evaluated_causes=['unknown_device','unknown_ip','geographic_anomaly','account_takeover'],
        labels='injected security scenarios; not real causal ground truth'), indent=2), encoding='utf-8')


def read_event(path, index):
    """Read one linked event without loading all histories into memory."""
    if index < 0:
        raise ValueError('Index negatif.')
    with Path(path).open(encoding='utf-8') as stream:
        for position, line in enumerate(stream):
            if position == index:
                return json.loads(line)
    raise ValueError('Numero hors du dataset. Choisir un index plus petit.')


def load_events(path):
    with Path(path).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data/banksim.csv')
    parser.add_argument('--output', default='data/investigation_synthetic.jsonl')
    parser.add_argument('--rows', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    generate(args.data, args.output, args.rows, args.seed)
    print(f'{args.rows} scénarios synthétiques écrits dans {args.output}')


if __name__ == '__main__':
    main()
