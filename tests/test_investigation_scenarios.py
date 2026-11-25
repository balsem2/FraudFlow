"""Controlled scenario coverage, not estimates of real-world causal accuracy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random
import unittest

from fraudflow.investigation import FraudInvestigationAgent, CAUSES, indicators


def baseline(seed):
    rng = random.Random(seed)
    now = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    amount = rng.uniform(20, 200)
    tx = dict(customer='C-test', merchant='M-known', category='food',
              amount=amount, step=151)
    history = [dict(tx, amount=amount, step=150,
                    timestamp=(now-timedelta(hours=2+i)).isoformat(),
                    device='device-known', ip='192.0.2.1', country='TN')
               for i in range(12)]
    return tx, dict(timestamp=now.isoformat(), history=history, device='device-known',
                   ip='192.0.2.1', country='TN', auth_failures_24h=0, synthetic=True)


class ControlledScenarioTests(unittest.TestCase):
    def evaluate(self, tx, context):
        # Explicit unit-test gate; production gate is independently tested elsewhere.
        return FraudInvestigationAgent().investigate(
            dict(alert=True, risk_score=.9, threshold=.4), tx, context)['causes']

    def test_each_cause_across_twenty_clients(self):
        for seed in range(20):
            for cause in CAUSES:
                with self.subTest(seed=seed, cause=cause):
                    tx, ctx = baseline(seed)
                    expected = {cause}
                    if cause == 'unusual_amount':
                        tx['amount'] *= 4
                    elif cause == 'new_merchant':
                        tx['merchant'] = 'M-new'
                    elif cause == 'new_category':
                        tx['category'] = 'travel'
                    elif cause == 'high_velocity':
                        now = datetime.fromisoformat(ctx['timestamp'])
                        for i in range(6):
                            ctx['history'][i]['timestamp'] = (now-timedelta(minutes=5+i)).isoformat()
                    elif cause == 'unknown_device':
                        ctx['device'] = 'new-device'
                    elif cause == 'unknown_ip':
                        ctx['ip'] = '203.0.113.1'
                    elif cause == 'geographic_anomaly':
                        ctx['country'] = 'FR'
                    else:
                        ctx.update(device='new-device', ip='203.0.113.1', auth_failures_24h=5)
                        expected |= {'unknown_device', 'unknown_ip'}
                    self.assertEqual(set(self.evaluate(tx, ctx)), expected)

    def test_twenty_normal_controls(self):
        for seed in range(20):
            with self.subTest(seed=seed):
                self.assertEqual(self.evaluate(*baseline(seed)), [])

    def test_takeover_requires_combined_evidence(self):
        for failures, device, ip in [(5, False, False), (5, True, False),
                                     (5, False, True), (2, True, True)]:
            tx, ctx = baseline(0)
            ctx['auth_failures_24h'] = failures
            if device:
                ctx['device'] = 'new'
            if ip:
                ctx['ip'] = '203.0.113.1'
            self.assertNotIn('account_takeover', self.evaluate(tx, ctx))

    def test_return_to_known_country_is_not_new(self):
        tx, ctx = baseline(0)
        ctx['history'][0]['country'] = 'FR'
        ctx['country'] = 'FR'
        self.assertNotIn('geographic_anomaly', self.evaluate(tx, ctx))

    def test_unknown_security_is_not_an_anomaly(self):
        tx, ctx = baseline(0)
        for h in ctx['history']:
            for key in ('device', 'ip', 'country'):
                h.pop(key)
        self.assertEqual(self.evaluate(tx, ctx), [])

    def test_future_events_cannot_hide_novelty(self):
        tx, ctx = baseline(0)
        ctx['country'] = 'FR'
        ctx['history'].append(dict(ctx['history'][0], country='FR',
                                   timestamp='2026-06-02T00:00:00+00:00'))
        self.assertIn('geographic_anomaly', self.evaluate(tx, ctx))

    def test_velocity_threshold_and_other_clients(self):
        tx, ctx = baseline(0)
        now = datetime.fromisoformat(ctx['timestamp'])
        for i in range(4):
            ctx['history'][i]['timestamp'] = (now-timedelta(minutes=i+1)).isoformat()
        ctx['history'].append(dict(ctx['history'][0], customer='someone-else'))
        self.assertNotIn('high_velocity', self.evaluate(tx, ctx))
        ctx['history'][4]['timestamp'] = (now-timedelta(minutes=5)).isoformat()
        self.assertIn('high_velocity', self.evaluate(tx, ctx))
        self.assertEqual(indicators(tx, ctx)['transactions_last_hour'], 5)

    def test_no_mutation_of_evidence(self):
        tx, ctx = baseline(0)
        saved = deepcopy((tx, ctx))
        self.evaluate(tx, ctx)
        self.assertEqual((tx, ctx), saved)
