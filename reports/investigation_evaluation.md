> Rapport historique v1 : ne decrit pas le dataset lie v2 regenere.
> Les labels v2 sont des references de regles, sans evaluation causale independante.

# Investigation synthétique — vérification du 12 novembre 2026

Le détecteur actif est XGBClassifier avec **500 arbres**, version `d62b64ccb62a`,
seuil **0,3404026031**. Son artefact n'a pas été réentraîné ni remplacé pendant
l'ajout de l'investigation. Les anciens résultats à 200 arbres et au seuil 0,4561
dans les rapports précédents décrivent une autre version.

Dataset complémentaire : 5 000 scénarios, seed 42, générateur
`fraudflow.synthetic_investigation`, historiques synthétiques de 12 événements.
Le score XGBoost est calculé avant toute enquête. Seulement **38 transactions**
ont déclenché une alerte ; les **4 962 autres** n'ont pas été investiguées.
Toutes les familles de causes ont un support non nul parmi ces 38 alertes.

| Mesure sur les alertes synthétiques | Valeur |
| --- | --- |
| Couverture d'investigation | 0,76 % |
| Micro-F1 multilabel | 0,9615 |
| Correspondance exacte des listes de causes | 89,47 % |
| Rappel high_velocity (3 occurrences) | 66,67 % |
| Rappel account_takeover (7 occurrences) | 57,14 % |

**Ces chiffres ne démontrent pas une précision causale réelle.** Les labels sont
des scénarios injectés, les règles et le générateur partagent des hypothèses,
le mock LLM est déterministe et l'échantillon d'alertes est petit. Il n'y a pas
de validation sur des dossiers annotés par des analystes, ni de confiance calibrée.
Les causes relatives à l'appareil/IP ne peuvent être investiguées si XGBoost
n'a pas signalé la transaction : ces variables ne font pas partie de son modèle.

Tests : 22 réussis, couvrant les fonctions historiques, la reprise du producteur,
la génération reproductible, l'exclusion des labels/événements futurs, le filtrage
des données sensibles, les huit causes, la validation des réponses LLM et le repli.
Contrôle de types Streamlit réussi. Interface exécutée avec le vrai modèle via
l'API locale de test Streamlit : score 0,999240, alerte, cause probable « montant
inhabituel », détails enregistrés dans une base de vérification séparée.

Bedrock est testé avec un faux client Converse et des erreurs simulées.
Aucun appel Bedrock réel ni déploiement AWS n'a été effectué.

Reproduction et limites : [guide d'investigation](../docs/investigation.md).
