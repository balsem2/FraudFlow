"""Evaluate synthetic cause hypotheses only after the real XGBoost alert gate."""
import argparse
import json
import hashlib
from pathlib import Path

from sklearn.metrics import classification_report, f1_score, accuracy_score
from sklearn.preprocessing import MultiLabelBinarizer

from fraudflow.dashboard_service import LocalScorer
from fraudflow.investigation import CAUSES, FraudInvestigationAgent, MockLLM
from fraudflow.synthetic_investigation import load_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data/investigation_synthetic.jsonl')
    parser.add_argument('--model', default='artifacts/model.joblib')
    parser.add_argument('--output', default='artifacts/investigation_metrics.json')
    args = parser.parse_args()
    scorer = LocalScorer(args.model, FraudInvestigationAgent(MockLLM()))
    truth, predictions, demo = [], [], None
    count = 0
    def iter_events():
        with Path(args.data).open(encoding='utf-8') as stream:
            for line in stream:
                yield json.loads(line)
    for event in iter_events():
        count += 1
        result = scorer.score(event['transaction'], event['context'])
        if result['alert']:
            truth.append(event['investigation_cause'])
            predictions.append(result['investigation']['causes'])
            if demo is None or result['risk_score'] > demo['result']['risk_score']:
                demo = {'event': event, 'result': result}
    with Path(args.data).open('rb') as stream:
        dataset_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = dict(scenarios=count, alerted=len(truth), not_investigated=count - len(truth),
                  dataset_sha256=dataset_hash,
                  agent_version=FraudInvestigationAgent.version, llm_mode='mock',
                  alert_coverage=len(truth) / count if count else 0,
                  model_version=scorer.version, threshold=scorer.threshold,
                  note='Synthetic rule/scenario consistency only; not real causal accuracy or calibrated confidence.')
    evaluated = ['unknown_device', 'unknown_ip', 'geographic_anomaly', 'account_takeover']
    report['evaluated_causes'] = evaluated
    report['note'] = 'Injected synthetic security scenarios only. Other hypotheses are unlabelled and excluded; not real causal accuracy.'
    truth = [[c for c in labels if c in evaluated] for labels in truth]
    predictions = [[c for c in labels if c in evaluated] for labels in predictions]
    if truth:
        encoder = MultiLabelBinarizer(classes=evaluated)
        expected = encoder.fit_transform(truth)
        predicted = encoder.transform(predictions)
        report.update(micro_f1=f1_score(expected, predicted, average='micro', zero_division=0),
                      exact_match=accuracy_score(expected, predicted),
                      per_cause=classification_report(expected, predicted, target_names=evaluated, output_dict=True, zero_division=0))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    if demo:
        (output.parent / 'investigation_demo.json').write_text(json.dumps(demo, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
