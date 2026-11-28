"""Run: python -m streamlit run app.py"""
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import pandas as pd
import streamlit as st

from fraudflow.aws_adapters import DynamoHistory, SageMakerScorer
from fraudflow.dashboard_service import LocalHistory, LocalScorer
from fraudflow.replay import load_transactions, replay_batch
from fraudflow.investigation_ui import render_investigation
from fraudflow.synthetic_investigation import read_event

ROOT = Path(__file__).resolve().parent
backend = os.getenv('FRAUDFLOW_BACKEND', 'local')
st.set_page_config(page_title='FraudFlow | Transactions', page_icon='◈', layout='wide')


@st.cache_resource
def load_scorer(path, modified, llm_mode, bedrock_model, backend, endpoint):
    if backend == 'aws':
        return SageMakerScorer(endpoint_name=endpoint)
    return LocalScorer(path)


@st.cache_resource
def load_history(backend, db_path):
    if backend == 'aws':
        return DynamoHistory()
    return LocalHistory(db_path)


st.title('FraudFlow')
st.caption('Détection de transactions suspectes · ' + ('AWS' if backend == 'aws' else 'Démonstration locale'))
model_path = Path(os.environ.get('FRAUDFLOW_MODEL_PATH', ROOT / 'artifacts/model.joblib'))
try:
    model_modified = model_path.stat().st_mtime_ns if backend == 'local' else None
    scorer = load_scorer(str(model_path), model_modified,
                         os.getenv('FRAUDFLOW_LLM_MODE', 'mock'),
                         os.getenv('FRAUDFLOW_BEDROCK_MODEL_ID', ''),
                         backend, os.getenv('FRAUDFLOW_SAGEMAKER_ENDPOINT', ''))
    history = load_history(backend, os.environ.get('FRAUDFLOW_DB_PATH', ROOT / 'artifacts/dashboard.sqlite3'))
except (OSError, ValueError, KeyError, sqlite3.Error) as error:
    st.error(f'Impossible de charger le modèle ou l’historique : {error}')
    st.info('Entraîner le modèle avec python -m fraudflow.train --data data/banksim.csv.')
    st.stop()

with st.sidebar:
    st.subheader('Centre de contrôle')
    st.write('Mode : AWS' if backend == 'aws' else 'Mode : local')
    if scorer.threshold is not None:
        st.metric('Seuil d’alerte', f'{scorer.threshold:.4f}')
    else:
        st.caption('Le seuil est renvoyé avec chaque score SageMaker.')
    st.caption(f'Modèle : {scorer.version}')
    st.info('Une alerte indique une transaction à examiner, pas une fraude confirmée.')
    if backend == 'aws':
        st.caption('Scoring SageMaker · Historique DynamoDB · Investigation Bedrock asynchrone.')
    else:
        st.caption('AWS : intégration à venir. Historique conservé sur cet ordinateur.')

form_tab, history_tab = st.tabs(['Analyser une transaction', 'Historique et statistiques'])
with form_tab:
    st.subheader('Nouvelle transaction')
    st.write('Renseignez les informations BankSim pour calculer un score de risque.')
    if backend == 'aws':
        linked = False
        st.caption('Saisie libre ; le score est calcule par SageMaker et l’historique est lu dans DynamoDB.')
    else:
        linked = st.checkbox('Choisir une transaction BankSim avec son historique lie', key='synthetic_context')
    if linked:
        st.caption('Historique BankSim ; appareils, IP et horaires simules. Transaction non modifiable dans ce mode.')
        event_index = st.number_input('Numero du scenario (a partir de 0)', min_value=0, value=0, step=1, key='linked_index')
        try:
            event = read_event(os.environ.get('FRAUDFLOW_SYNTHETIC_PATH', str(ROOT / 'data/investigation_synthetic.jsonl')), event_index)
            st.json(event['transaction'])
            st.caption('Horaire simule : ' + event['context'].get('timestamp', 'indisponible'))
            if st.button('Analyser cette transaction liee', key='analyze_linked', type='primary'):
                record = scorer.score(event['transaction'], event['context'])
                history.add(record)
                st.session_state['last_prediction'] = record
        except (OSError, ValueError, sqlite3.Error) as error:
            st.error(f'Transaction liee indisponible : {error}')
    else:
        st.caption('Saisie libre : historique local disponible, sans contexte artificiel ajoute.')
        with st.form('transaction'):
            left, right = st.columns(2)
            with left:
                amount = st.number_input('Montant', min_value=0.0, value=125.5, step=10.0, key='amount')
                step = st.number_input('Step (jour simulé)', min_value=0, value=180, step=1, key='step')
                customer = st.text_input('Identifiant client', 'C1093826151', key='customer')
                merchant = st.text_input('Identifiant commerçant', 'M348934600', key='merchant')
            with right:
                category = st.selectbox('Catégorie', [
                    'es_transportation', 'es_food', 'es_health', 'es_wellnessandbeauty',
                    'es_fashion', 'es_barsandrestaurants', 'es_hyper', 'es_sportsandtoys',
                    'es_tech', 'es_home', 'es_hotelservices', 'es_otherservices',
                    'es_contents', 'es_travel', 'es_leisure'], key='category')
                age = st.selectbox('Code de tranche d’âge', ['0', '1', '2', '3', '4', '5', '6', 'U'], index=3)
                gender = st.selectbox('Code de genre', ['F', 'M', 'E', 'U'])
                zip_left, zip_right = st.columns(2)
                zipcode = zip_left.text_input('Code postal client', '28007')
                zipmerchant = zip_right.text_input('Code postal commerçant', '28007')
            submitted = st.form_submit_button('Analyser la transaction', type='primary')
        if submitted:
            try:
                transaction = dict(amount=amount, step=step, customer=customer,
                                           merchant=merchant, category=category, age=age,
                                           gender=gender, zipcodeOri=zipcode, zipMerchant=zipmerchant)
                record = scorer.score_with_history(transaction, history)
                history.add(record)
                st.session_state['last_prediction'] = record
            except (ValueError, sqlite3.Error, OSError) as error:
                st.session_state.pop('last_prediction', None)
                st.error(f'Transaction non enregistrée : {error}')
    if 'last_prediction' in st.session_state:
        last = st.session_state['last_prediction']
        st.subheader('Dernier résultat enregistré')
        score_col, threshold_col = st.columns(2)
        score_col.metric('Score de risque (0–1)', f"{last['risk_score']:.6f}")
        threshold_col.metric('Seuil appliqué', f"{last['threshold']:.4f}")
        st.progress(min(max(last['risk_score'], 0.0), 1.0))
        if last['alert']:
            st.warning('Alerte — transaction à examiner.')
        else:
            st.success('Aucune alerte au seuil appliqué.')
        st.caption('Le score n’est pas une probabilité calibrée garantie.')
        render_investigation(last)

@st.fragment(run_every=2)
def live_history():
    if backend == 'aws':
        st.info('Mode AWS : le producteur Kinesis se lance depuis le terminal avec python -m fraudflow.aws_producer.')
    elif os.environ.get('FRAUDFLOW_EXTERNAL_PRODUCER') == '1':
        st.info('Producteur indépendant : les nouvelles transactions apparaissent automatiquement. Le démarrage et l’arrêt se font dans le terminal.')
    else:
        st.subheader('Simulation BankSim')
        st.caption('Rejeu chronologique des steps 144–179, déjà utilisés pour le test. '
                   'Les labels fraud ne sont pas transmis au modèle. Ce n’est pas un flux AWS.')
        state = st.session_state
        state.setdefault('replay_running', False)
        state.setdefault('replay_cursor', 0)
        source = st.selectbox('Source du rejeu', ['BankSim', 'BankSim + contexte synthétique'],
                              key='replay_source', disabled=state.replay_running)
        if state.get('loaded_replay_source', source) != source:
            state.pop('replay_data', None)
            state.replay_cursor = 0
        state.loaded_replay_source = source
        size = st.selectbox('Transactions par lot (toutes les 2 secondes environ)', [5, 10, 25, 50], key='replay_size')
        start, stop, reset = st.columns(3)
        if start.button('Démarrer / Reprendre', key='replay_start', disabled=state.replay_running):
            try:
                if 'replay_data' not in state:
                    path = (os.environ.get('FRAUDFLOW_SYNTHETIC_PATH', str(ROOT / 'data/investigation_synthetic.jsonl'))
                            if source != 'BankSim' else os.environ.get('FRAUDFLOW_DATA_PATH', str(ROOT / 'data/banksim.csv')))
                    state.replay_data = load_transactions(path)
                    state.replay_run = str(uuid4())
                if state.replay_cursor < len(state.replay_data):
                    state.replay_running = True
                    state.replay_next = time.monotonic()
                else:
                    st.info('Fin du fichier. Utilisez « Nouvelle simulation » pour recommencer.')
            except (OSError, ValueError) as error:
                st.error(f'Impossible de lire BankSim : {error}')
        if stop.button('Pause', key='replay_stop', disabled=not state.replay_running):
            state.replay_running = False
        if reset.button('Nouvelle simulation', key='replay_reset', disabled=state.replay_running):
            state.replay_cursor = 0
            state.replay_run = str(uuid4())
            st.info('Position remise au début. L’historique précédent est conservé.')
        if state.replay_running and time.monotonic() >= state.get('replay_next', 0):
            try:
                state.replay_cursor = replay_batch(state.replay_data, state.replay_cursor,
                                                   size, state.replay_run, scorer, history)
                state.replay_next = time.monotonic() + 2
                if state.replay_cursor >= len(state.replay_data):
                    state.replay_running = False
            except (ValueError, OSError, sqlite3.Error) as error:
                state.replay_running = False
                st.error(f'Simulation interrompue : {error}')
        if 'replay_data' in state:
            total = len(state.replay_data)
            st.progress(state.replay_cursor / total if total else 0)
            status = 'En cours' if state.replay_running else ('Terminée' if state.replay_cursor >= total else 'En pause')
            st.write(f'{status} · {state.replay_cursor:,} / {total:,} transactions rejouées')
        st.caption('Le rejeu fonctionne pendant la session ouverte. Pause conserve la position ; '
                   'un rechargement complet peut réinitialiser la session. Les analyses restent enregistrées.')
    st.subheader('Historique des analyses')
    st.button('Actualiser')
    records = history.recent()
    st.caption('Statistiques sur les 1 000 dernières analyses enregistrées au maximum. Horodatages en UTC.')
    if not records:
        st.info('Aucune transaction analysée. Utilisez le formulaire pour commencer.')
    else:
        frame = pd.DataFrame(records)
        frame['cause_probable'] = [r.get('investigation', {}).get('probable_cause', '') for r in records]
        frame['confiance'] = [r.get('investigation', {}).get('confidence', '') for r in records]
        cols = st.columns(4)
        cols[0].metric('Transactions', len(frame))
        cols[1].metric('Alertes', int(frame.alert.sum()))
        cols[2].metric('Taux d’alerte', f'{frame.alert.mean():.1%}')
        cols[3].metric('Montant total', f'{frame.amount.sum():,.2f}')
        alerts_only = st.checkbox('Afficher uniquement les alertes', key='alerts_only')
        shown = frame[frame.alert] if alerts_only else frame
        st.dataframe(shown[['created_at', 'customer', 'merchant', 'amount', 'category',
                           'risk_score', 'threshold', 'alert', 'model_version', 'cause_probable', 'confiance']], hide_index=True,
                     width='stretch')
        st.bar_chart(frame.groupby('category')['alert'].sum().rename('Alertes par catégorie'))
        export = shown.drop(columns=['investigation'], errors='ignore')
        st.download_button('Exporter la sélection en CSV', export.to_csv(index=False).encode('utf-8-sig'),
                           file_name='fraudflow_transactions.csv', mime='text/csv')
        investigations = [r for r in records if r.get('investigation')]
        if investigations:
            selected = st.selectbox('Consulter une investigation', [r['id'] for r in investigations], key='investigation_detail')
            record = next(r for r in investigations if r['id'] == selected)
            st.write(f"Score {record['risk_score']:.4f} · Seuil {record['threshold']:.4f} · Décision : alerte")
            render_investigation(record)


with history_tab:
    live_history()
