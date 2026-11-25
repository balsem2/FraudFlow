import json
from pathlib import Path
import random
import tempfile
import unittest

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier

from fraudflow.dashboard_service import LocalScorer
from fraudflow.investigation import FraudInvestigationAgent, MockLLM, BedrockLLM, indicators
from fraudflow.model import features, pipeline
from fraudflow.replay import load_transactions
from fraudflow.synthetic_investigation import generate, load_events, make_context

TX = dict(step=144, amount=900, customer='private-customer', merchant='private-merchant',
          age='3', gender='F', zipcodeOri='28007', zipMerchant='28007', category='es_travel')
DECISION = dict(alert=True, risk_score=0.9, threshold=0.45)


class InvestigationTests(unittest.TestCase):
    def test_all_eight_causes_can_coexist(self):
        from datetime import timedelta
        from fraudflow.investigation import CAUSES, timestamp
        context = make_context(TX, list(CAUSES), random.Random(42))
        context['auth_failures_24h'] = 5
        for index, event in enumerate(context['history']):
            event['amount'] = 100
            event['timestamp'] = (timestamp(context['timestamp']) - timedelta(minutes=index + 1)).isoformat()
        result = FraudInvestigationAgent().investigate(DECISION, TX, context)
        self.assertEqual(set(result['causes']), set(CAUSES))

    def test_llm_cannot_override_decision(self):
        class Override(MockLLM):
            def generate(self, evidence):
                return dict(super().generate(evidence), alert=False, risk_score=0)
        result = FraudInvestigationAgent(Override()).investigate(DECISION, TX)
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(DECISION, dict(alert=True, risk_score=0.9, threshold=0.45))

    def test_future_and_other_customers_excluded(self):
        context = make_context(TX, [], random.Random(1))
        original = indicators(TX, context)
        context['history'].extend([
            dict(context['history'][0], timestamp='2030-01-01T00:00:00+00:00', amount=1e6),
            dict(context['history'][0], customer='someone-else', amount=1e6)])
        self.assertEqual(original, indicators(TX, context))

    def test_labels_not_used_or_sent_and_sensitive_values_not_sent(self):
        class Spy(MockLLM):
            def generate(self, evidence):
                self.payload = json.dumps(evidence)
                return super().generate(evidence)
        llm = Spy()
        context = make_context(TX, ['account_takeover'], random.Random(42))
        context['auth_failures_24h'] = 5
        agent = FraudInvestigationAgent(llm)
        result = agent.investigate(DECISION, dict(TX, fraud=1, investigation_cause=['made-up']), context)
        self.assertIn('account_takeover', result['causes'])
        for sensitive in ['private-customer', 'private-merchant', '192.0.2.', '203.0.113.', 'synthetic-device', 'investigation_cause', 'made-up']:
            self.assertNotIn(sensitive, llm.payload)
        self.assertEqual(result, agent.investigate(DECISION, dict(TX, fraud=0, investigation_cause=[]), context))

    def test_no_alert_rejected_and_missing_history_abstains(self):
        agent = FraudInvestigationAgent()
        with self.assertRaises(ValueError):
            agent.investigate(dict(DECISION, alert=False), TX)
        result = agent.investigate(DECISION, TX)
        self.assertEqual(result['causes'], [])
        self.assertEqual(result['confidence'], 'faible')

    def test_bad_llm_falls_back_without_changing_decision(self):
        class Bad(MockLLM):
            def generate(self, evidence):
                return dict(causes=['invented'], confidence='certain', explanation='secret', action='block')
        result = FraudInvestigationAgent(Bad()).investigate(DECISION, TX)
        self.assertEqual(result['status'], 'degraded')
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('alert', result)
        self.assertEqual(DECISION['risk_score'], 0.9)

    def test_bedrock_adapter_and_timeout_fallback(self):
        class Client:
            def converse(self, **kwargs):
                self.request = kwargs
                return {'output': {'message': {'content': [{'text': json.dumps(MockLLM().generate(json.loads(kwargs['messages'][0]['content'][0]['text'])))}]}}}
        client = Client()
        agent = FraudInvestigationAgent(BedrockLLM('test-model', client=client))
        self.assertEqual(agent.investigate(DECISION, TX)['backend'], 'bedrock')
        self.assertEqual(client.request['modelId'], 'test-model')
        class Timeout(MockLLM):
            def generate(self, evidence):
                raise TimeoutError('sensitive-provider-response')
        result = FraudInvestigationAgent(Timeout()).investigate(DECISION, TX)
        self.assertEqual(result['backend'], 'mock_fallback')
        self.assertNotIn('sensitive-provider-response', json.dumps(result))

    def test_scorer_gate_does_not_call_agent_for_normal_transaction(self):
        class Spy:
            def investigate(self, *args):
                raise AssertionError('Must not be called')
        with tempfile.TemporaryDirectory() as temp:
            model = pipeline()
            model.set_params(model=DummyClassifier(strategy='constant', constant=0))
            model.fit(features(pd.DataFrame([TX, TX])), [0, 1])
            path = Path(temp) / 'model.joblib'
            joblib.dump(dict(pipeline=model, threshold=0.45), path)
            result = LocalScorer(path, Spy()).score(TX)
            self.assertFalse(result['alert'])
            self.assertNotIn('investigation', result)

    def test_generator_reproducible_and_replay_strips_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            pd.DataFrame([dict(TX, fraud=1)]).to_csv(path / 'source.csv', index=False)
            generate(path / 'source.csv', path / 'a.jsonl', 1, 42)
            generate(path / 'source.csv', path / 'b.jsonl', 1, 42)
            self.assertEqual((path / 'a.jsonl').read_bytes(), (path / 'b.jsonl').read_bytes())
            replay = load_transactions(path / 'a.jsonl')
            self.assertNotIn('fraud', replay)
            self.assertNotIn('investigation_cause', replay)
            self.assertEqual(len(load_events(path / 'a.jsonl')), 1)
            self.assertNotIn('investigation_cause', features(replay))

    def test_linked_history_uses_source_and_excludes_same_day_future_other_client(self):
        from fraudflow.synthetic_investigation import identified_transactions
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            records = [dict(TX, step=140, amount=10), dict(TX, step=143, amount=30),
                       dict(TX, step=143, customer='other', amount=999),
                       dict(TX, step=144, amount=90), dict(TX, step=144, amount=120),
                       dict(TX, step=145, amount=200)]
            source = path / 'source.csv'
            pd.DataFrame(records).to_csv(source, index=False)
            generate(source, path / 'a.jsonl', 3, 42)
            events = load_events(path / 'a.jsonl')
            identified, _ = identified_transactions(source)
            ids = set(identified.transaction_id)
            self.assertEqual(len(ids), len(records))
            for event in events:
                tx, ctx = event['transaction'], event['context']
                self.assertIn(tx['transaction_id'], ids)
                expected = [r for r in records if r['customer']==tx['customer'] and r['step']<tx['step']]
                self.assertEqual(sorted(r['amount'] for r in ctx['history'] if r['step'] < tx['step']), sorted(r['amount'] for r in expected))
                self.assertTrue(all(h['timestamp'] < ctx['timestamp'] for h in ctx['history']))
                self.assertTrue(all(h['transaction_id'] in ids for h in ctx['history']))
                self.assertEqual(ctx['timestamp_source'], 'simulated_intraday')
                self.assertNotIn('risk_score', ctx['history'][0])
                self.assertIsInstance(indicators(tx, ctx)['transactions_last_hour'], int)
            self.assertEqual(indicators(events[0]['transaction'], events[0]['context'])['mean_amount'],20)
            # Previously emitted security context is retained in later client history.
            first = events[0]
            stored = next(h for h in events[-1]['context']['history'] if h['transaction_id']==first['transaction_id'])
            for field in ['device','ip','country','auth_failures_24h']:
                self.assertEqual(stored[field], first['context'][field])
            # Selecting fewer rows cannot change a transaction's simulated context.
            generate(source, path / 'b.jsonl', 1, 42)
            subset = load_events(path / 'b.jsonl')[0]
            self.assertEqual(subset, next(e for e in events if e['transaction_id']==subset['transaction_id']))
            replay = load_transactions(path / 'a.jsonl')
            self.assertEqual(set(replay.transaction_id), {e['transaction_id'] for e in events})
            self.assertNotIn('transaction_id', features(replay))
            with self.assertRaises(ValueError):
                generate(source, path / 'c.jsonl', 4, 42)

    def test_injection_labels_do_not_call_detector_rules(self):
        from unittest.mock import patch
        from fraudflow.synthetic_investigation import read_event
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            pd.DataFrame([dict(TX, step=140), TX]).to_csv(path/'source.csv', index=False)
            with patch('fraudflow.investigation.probable_causes', side_effect=AssertionError('label leakage')):
                generate(path/'source.csv', path/'events.jsonl', 1)
            event=read_event(path/'events.jsonl', 0)
            self.assertEqual(event['label_source'], 'injected_security_scenario_not_real_fraud')
            with self.assertRaises(ValueError):
                read_event(path/'events.jsonl', 1)

    def test_hourly_counter_boundaries(self):
        ctx=dict(timestamp='2026-06-01T12:00:00+00:00', history=[
            dict(TX, timestamp=t) for t in ['2026-06-01T11:00:00+00:00',
              '2026-06-01T10:59:59+00:00', '2026-06-01T12:00:00+00:00',
              '2026-06-01T12:01:00+00:00']])
        self.assertEqual(indicators(TX,ctx)['transactions_last_hour'],1)
