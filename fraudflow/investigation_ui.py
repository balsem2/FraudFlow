"""Presentation only. No scoring, history access or LLM calls here."""
import streamlit as st


def render_investigation(record):
    investigation = record.get('investigation')
    if not investigation:
        st.caption('Investigation non déclenchée ou indisponible pour cette ancienne analyse.')
        return
    st.subheader('Investigation après alerte')
    st.write(f"Cause probable : {investigation.get('probable_cause', 'indéterminée')}")
    st.write(f"Confiance : {investigation.get('confidence', 'faible')} — appréciation non calibrée")
    st.text(investigation.get('explanation', ''))
    st.write('Action recommandée : ' + investigation.get('recommendation', 'Examen manuel.'))
    st.caption(f"Mode : {investigation.get('backend', 'indisponible')} · État : {investigation.get('status')} · "
               f"Contexte : {investigation.get('context_source', 'inconnu')}. Aucune action exécutée automatiquement.")
    if investigation.get('timestamp_source') == 'simulated_intraday':
        st.info('Vitesse horaire calculee sur des horaires simules, pas sur des heures observees dans BankSim.')
    if investigation.get('indicators'):
        with st.expander('Indicateurs calculés sur l’historique antérieur'):
            st.json(investigation['indicators'])
    if investigation.get('model_factors'):
        st.caption('Importances globales XGBoost : ni contributions locales SHAP ni preuve de causalité.')
        st.dataframe(investigation['model_factors'], hide_index=True,
                     alt='Principales variables selon les importances globales du modèle')
