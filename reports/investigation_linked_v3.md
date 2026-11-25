# Investigation liee v3 - verification locale

- Dataset : 5000 transactions BankSim distinctes, contexte lie.
- Agent : investigation-v3 ; LLM mock.
- XGBoost : modele d62b64ccb62a, seuil 0.34040260314941406.
- Alertes : 51 ; non investiguees : 4949.
- Empreinte dataset : `4b0fc859d29a44a27fc16d23eed45582354aac28ce19852e3f393005a56e82e7` (verifiee).

## Interpretation

Micro-F1 et exact match : 1.00 et 1.00,
uniquement sur quatre scenarios de securite injectes et sur les alertes XGBoost.
Ce resultat n'est pas une performance causale reelle. Les scenarios sont synthetiques
et proches des indices utilises par les regles ; les supports sont tres faibles.

| Scenario | Support parmi les alertes |
| --- | --- |
| unknown_device | 8 |
| unknown_ip | 1 |
| geographic_anomaly | 0 |
| account_takeover | 1 |

Une classe sans support n'est pas evaluable. Montant inhabituel, nouveau merchant,
nouvelle categorie et vitesse ne disposent pas de labels independants et sont exclus
de ces metriques. Le LLM explique les indices ; il ne prouve pas une cause.

## Verifications

25 tests reussis. Verification de type Streamlit reussie. Interface testee dans
un serveur local isole : selection d'une transaction liee, score et enregistrement.
5000 historiques controles : meme client, timestamps strictement anterieurs.
Le maximum observe est une transaction anterieure dans l'heure : aucun scenario
de rafale dans cet echantillon. Les frontieres du compteur horaire sont testees.

Les heures sont simulees dans les jours BankSim, jamais presentees comme observees.
La saisie libre ne fabrique plus d'historique. Les identifiants et labels restent
exclus des features XGBoost. Aucun deploiement AWS ni reentrainement du detecteur.
