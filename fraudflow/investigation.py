"""Post-alert hypotheses, never a replacement for the detector decision."""
from datetime import datetime, timezone
import json
import math
import os

CAUSES = {
    'unusual_amount': 'montant inhabituel',
    'new_merchant': 'nouveau commerçant',
    'high_velocity': 'vitesse élevée de transactions',
    'new_category': 'nouvelle catégorie',
    'unknown_device': 'appareil inconnu',
    'unknown_ip': 'adresse IP inconnue',
    'geographic_anomaly': 'localisation inhabituelle',
    'account_takeover': 'prise de contrôle de compte possible',
}
ACTIONS = {
    'manual_review': 'Faire examiner la transaction par un analyste.',
    'verify_identity': 'Proposer une vérification d’identité renforcée et examiner les accès récents.',
}
DISCLAIMER = 'Cause probable uniquement, à confirmer par un analyste ; la décision XGBoost reste inchangée.'


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def indicators(transaction, context):
    """Only prior events for this customer; raw identifiers never leave this function."""
    context = context if isinstance(context, dict) else {}
    now = timestamp(context.get('timestamp'))
    previous = []
    for event in context.get('history', []):
        if event.get('customer') != transaction.get('customer'):
            continue
        when = timestamp(event.get('timestamp'))
        # BankSim has day steps only; no fabricated sub-day velocity for real CSVs.
        before = (when < now) if now and when else (
            number(event.get('step')) is not None and float(event['step']) < float(transaction['step']))
        if before and number(event.get('amount')) is not None:
            previous.append(event)
    amounts = [float(event['amount']) for event in previous]
    average = sum(amounts) / len(amounts) if amounts else None
    merchant_events = [event for event in previous if event.get('merchant') == transaction.get('merchant')]
    risks = [number(event.get('risk_score')) for event in previous]
    risks = [risk for risk in risks if risk is not None and risk <= 1]
    result = {
        'history_count': len(previous), 'mean_amount': average,
        'amount_ratio': float(transaction['amount']) / average if average and average > 0 else None,
        'merchant_history_count': len(merchant_events),
        'merchant_mean_amount': sum(float(e['amount']) for e in merchant_events) / len(merchant_events) if merchant_events else None,
        'prior_mean_risk': sum(risks) / len(risks) if risks else None,
        'prior_high_risk_rate_at_0_5': sum(r >= 0.5 for r in risks) / len(risks) if risks else None,
        'merchant_mean_risk': None,
        'transactions_last_hour': sum(0 < (now - timestamp(e['timestamp'])).total_seconds() <= 3600
                                      for e in previous if timestamp(e.get('timestamp'))) if now else None,
        'auth_failures_24h': number(context.get('auth_failures_24h')),
    }
    merchant_risks = [number(e.get('risk_score')) for e in merchant_events]
    merchant_risks = [r for r in merchant_risks if r is not None and r <= 1]
    if merchant_risks:
        result['merchant_mean_risk'] = sum(merchant_risks) / len(merchant_risks)
    for label, current, field in [
        ('new_merchant', transaction.get('merchant'), 'merchant'),
        ('new_category', transaction.get('category'), 'category'),
        ('unknown_device', context.get('device'), 'device'),
        ('unknown_ip', context.get('ip'), 'ip'),
        ('geographic_anomaly', context.get('country'), 'country'),
    ]:
        known = {e.get(field) for e in previous if e.get(field) is not None}
        result[label] = current not in known if current is not None and known else None
    return result


def probable_causes(values):
    causes = [key for key in ('new_merchant', 'new_category', 'unknown_device', 'unknown_ip', 'geographic_anomaly')
              if values.get(key) is True]
    if values.get('amount_ratio') is not None and values['amount_ratio'] >= 3:
        causes.append('unusual_amount')
    if values.get('transactions_last_hour') is not None and values['transactions_last_hour'] >= 5:
        causes.append('high_velocity')
    if ((values.get('auth_failures_24h') or 0) >= 3 and values.get('unknown_device') is True
            and (values.get('unknown_ip') is True or values.get('geographic_anomaly') is True)):
        causes.append('account_takeover')
    return sorted(causes)


class MockLLM:
    name = 'mock'

    def generate(self, evidence):
        causes = evidence['candidate_causes']
        return dict(causes=causes, confidence='modérée' if causes else 'faible',
                    explanation='Indices compatibles avec : ' + ', '.join(CAUSES[c] for c in causes)
                    if causes else 'Historique insuffisant ou aucun indicateur explicatif identifié.',
                    action='verify_identity' if 'account_takeover' in causes else 'manual_review')


class BedrockLLM:
    name = 'bedrock'

    def __init__(self, model_id, region=None, client=None):
        if not model_id:
            raise ValueError('FRAUDFLOW_BEDROCK_MODEL_ID requis.')
        self.model_id, self.region, self.client = model_id, region, client

    def generate(self, evidence):
        if self.client is None:
            import boto3
            from botocore.config import Config
            self.client = boto3.client('bedrock-runtime', region_name=self.region,
                                       config=Config(connect_timeout=3, read_timeout=15,
                                                     retries={'max_attempts': 1}))
        response = self.client.converse(
            modelId=self.model_id,
            system=[{'text': 'Tu expliques uniquement des hypothèses après une alerte XGBoost. '
                      'Ne change jamais score, seuil ou décision. Aucune action automatique. '
                      'Ne conclus jamais à une fraude certaine. Les importances sont globales, non causales. '
                      'Utilise seulement les indicateurs fournis. Réponds en JSON strict : '
                      '{"causes": [codes parmi candidate_causes], "confidence": "faible" ou "modérée", '
                      '"explanation": "explication courte en français", '
                      '"action": "manual_review" ou "verify_identity"}. '
                      'Sans indice, causes=[] et confidence=faible.'}],
            messages=[{'role': 'user', 'content': [{'text': json.dumps(evidence, allow_nan=False)}]}],
            inferenceConfig={'maxTokens': 500, 'temperature': 0},
        )
        text = ''.join(block.get('text', '') for block in response['output']['message']['content'])
        return json.loads(text)


def configured_llm():
    mode = os.getenv('FRAUDFLOW_LLM_MODE', 'mock')
    if mode == 'mock':
        return MockLLM()
    if mode != 'bedrock':
        raise ValueError('FRAUDFLOW_LLM_MODE doit être mock ou bedrock.')
    return BedrockLLM(os.getenv('FRAUDFLOW_BEDROCK_MODEL_ID'),
                      os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION'))


class FraudInvestigationAgent:
    version = 'investigation-v3'

    def __init__(self, llm=None):
        self.llm = llm or MockLLM()

    def investigate(self, decision, transaction, context=None, model_factors=None):
        if not decision.get('alert'):
            raise ValueError('Investigation réservée aux transactions signalées.')
        values = indicators(transaction, context)
        candidates = probable_causes(values)
        factors = [{'feature': f['feature'], 'importance': float(f['importance'])}
                   for f in (model_factors or []) if f.get('feature') in
                   ('step', 'amount', 'customer', 'merchant', 'age', 'gender', 'category', 'zipcodeOri', 'zipMerchant')]
        evidence = dict(indicators=values, candidate_causes=candidates, global_model_factors=factors,
                        risk_score=float(decision['risk_score']), threshold=float(decision['threshold']))
        backend, status = self.llm.name, 'completed'
        try:
            answer = self.llm.generate(evidence)
            if (not isinstance(answer, dict) or set(answer) != {'causes', 'confidence', 'explanation', 'action'}
                    or not isinstance(answer.get('causes'), list)
                    or any(c not in candidates for c in answer['causes'])
                    or answer.get('confidence') not in ('faible', 'modérée')
                    or answer.get('action') not in ACTIONS
                    or not isinstance(answer.get('explanation'), str)
                    or not 0 < len(answer['explanation']) <= 2000):
                raise ValueError('Réponse LLM invalide.')
            if not answer['causes']:
                answer['confidence'] = 'faible'
        except Exception:
            # Do not persist provider exceptions: they may contain payloads/identifiers.
            answer = MockLLM().generate(evidence)
            backend, status = 'mock_fallback', 'degraded'
        return dict(status=status, agent_version=self.version, backend=backend,
                    context_source='synthetic' if (context or {}).get('synthetic') is True else 'observed_or_missing',
                    timestamp_source=(context or {}).get('timestamp_source', 'unavailable'),
                    indicators=values, causes=sorted(set(answer['causes'])),
                    probable_cause=', '.join(CAUSES[c] for c in answer['causes']) or 'indéterminée',
                    confidence=answer['confidence'], confidence_note='Appréciation heuristique, non calibrée.',
                    explanation=DISCLAIMER + ' ' + answer['explanation'],
                    recommendation=ACTIONS[answer['action']], model_factors=factors,
                    factor_method='global_feature_importances_not_local_causality')
