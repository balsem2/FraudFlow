"""Verify AWS configuration; --invoke explicitly tests one real investigation."""
import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', default=os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION'))
    parser.add_argument('--model-id', default=os.getenv('FRAUDFLOW_BEDROCK_MODEL_ID'))
    parser.add_argument('--invoke', action='store_true')
    parser.add_argument('--index', type=int, default=66)
    parser.add_argument('--data', default='data/investigation_synthetic.jsonl')
    parser.add_argument('--model', default='artifacts/model.joblib')
    args = parser.parse_args()
    try:
        import boto3
        session = boto3.Session(region_name=args.region)
        # Do not query EC2 instance metadata on a local workstation.
        if not os.getenv('AWS_EXECUTION_ENV'):
            os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')
        credentials = session.get_credentials()
    except Exception as error:
        parser.exit(1, f'AWS configuration unavailable ({type(error).__name__}). No credentials printed.\n')
    status = dict(region_configured=bool(session.region_name), model_configured=bool(args.model_id),
                  credentials_configured=credentials is not None, invoked=False)
    print(json.dumps(status))
    if not all(status[k] for k in ('region_configured', 'model_configured', 'credentials_configured')):
        parser.exit(1, 'Configure AWS credentials, region and FRAUDFLOW_BEDROCK_MODEL_ID locally.\n')
    if not args.invoke:
        print('Configuration present; permissions and model access NOT verified. Use --invoke for a real call.')
        return
    from fraudflow.dashboard_service import LocalScorer
    from fraudflow.investigation import BedrockLLM, FraudInvestigationAgent
    from fraudflow.synthetic_investigation import read_event
    event = read_event(args.data, args.index)
    agent = FraudInvestigationAgent(BedrockLLM(args.model_id, session.region_name))
    result = LocalScorer(args.model, agent).score(event['transaction'], event['context'])
    investigation = result.get('investigation', {})
    print(json.dumps(dict(score=result['risk_score'], threshold=result['threshold'],
                          alert=result['alert'], investigation=investigation), ensure_ascii=True, indent=2))
    if investigation.get('backend') != 'bedrock' or investigation.get('status') != 'completed':
        parser.exit(1, 'Real Bedrock response NOT validated (no alert, provider failure or invalid response).\n')
    print('PASS: real Bedrock response validated; XGBoost decision preserved.')


if __name__ == '__main__':
    main()
