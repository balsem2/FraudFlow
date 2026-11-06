# FraudFlow

Projet pédagogique de détection de transactions suspectes combinant AWS,
Machine Learning et MLOps.

## État du projet

Première baseline exécutée localement le 5 novembre 2026 : analyse BankSim,
entraînement XGBoost, évaluation chronologique et prédiction JSON fonctionnent.
Le modèle local est dans `artifacts/model.joblib` (non versionné).
Le dashboard Streamlit local est disponible ; les services AWS restent à construire. Les documents du brief
restent à analyser ; l'architecture ci-dessous suit le résumé fourni.

## Architecture cible

Python / BankSim → Kinesis → Lambda → SageMaker / XGBoost → DynamoDB
→ Streamlit sur ECS Fargate. Terraform, GitHub Actions et CloudWatch assureront
le déploiement et la supervision. Kinesis est retenu selon le résumé fourni ;
confirmer Kafka uniquement si l'encadrement l'impose.

## Dashboard local

Installer les dépendances verrouillées puis lancer depuis la racine :

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements-lock.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Ouvrir http://localhost:8501. Le formulaire accepte les neuf features BankSim,
calcule le score avec le modèle local et enregistre la transaction. Le second
onglet affiche les statistiques sur les 1 000 dernières analyses, un filtre
d'alertes, un graphique par catégorie et un export CSV de la sélection.
Une alerte n'est pas un label de fraude confirmé. Aucun historique fictif n'est
préchargé. Les horodatages sont en UTC ; les montants gardent l'unité du dataset.

L'historique persiste dans `artifacts/dashboard.sqlite3`, même après redémarrage.
Il est commun aux sessions de cette application locale. Les variables
`FRAUDFLOW_MODEL_PATH` et `FRAUDFLOW_DB_PATH` permettent de choisir les chemins.
Le modèle est rechargé quand le fichier change ; chaque prédiction conserve son
seuil et l'empreinte du modèle. Ne fournir que des modèles joblib de confiance.

`fraudflow/dashboard_service.py` sépare le calcul du score et le stockage de
l'interface. Pour AWS, remplacer ces adaptateurs par l'intégration du flux
Kinesis/Lambda/SageMaker et la lecture DynamoDB, puis conteneuriser Streamlit
sur ECS Fargate. SQLite n'est pas le stockage cible sur Fargate. Aucune ressource
AWS n'est déployée et l'application locale n'inclut pas d'authentification.

Les tests d'interface utilisent [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
avec un modèle de test et une base temporaire. Ils vérifient soumission,
persistance, filtre, saisie invalide et modèle absent sans polluer l'historique réel.

## Première exécution locale

### Simulation dans le dashboard

Dans « Historique et statistiques », cliquer « Démarrer / Reprendre ». Le flux
rejoue les steps >= 144 de BankSim dans l'ordre chronologique, sans utiliser le
label `fraud`. Choisir 5, 10, 25 ou 50 transactions par lot, espacés d'environ
deux secondes (le calcul peut allonger cet intervalle). Le flux s'arrête en fin
de données ; « Pause » conserve la position. « Nouvelle simulation » repart du
début avec un nouvel identifiant sans effacer l'historique précédent.

Le timer utilise [les fragments Streamlit](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment).
La session doit rester ouverte ; un rechargement complet peut réinitialiser sa
position. Plusieurs onglets navigateur créent des simulations indépendantes.
Les lots sont enregistrés atomiquement, avec des IDs stables pour éviter les
doublons lors d'une nouvelle tentative du même lot. Le chemin du CSV peut être
configuré par `FRAUDFLOW_DATA_PATH`. Les tableaux se rafraîchissent automatiquement.
Il s'agit d'une démonstration locale sur des données déjà évaluées, pas d'une
nouvelle mesure de généralisation ni d'un producteur Kinesis encore déployé.

Prérequis : Python 3.12. Depuis la racine du projet, sous PowerShell :

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-lock.txt
# Placer le CSV BankSim obtenu légalement dans data/banksim.csv.
.\.venv\Scripts\python.exe -m fraudflow.analyze --data data/banksim.csv
.\.venv\Scripts\python.exe -m fraudflow.train --data data/banksim.csv
.\.venv\Scripts\python.exe -m fraudflow.predict --transaction examples/transaction.json
```

Schéma attendu : `step`, `amount`, `customer`, `age`, `gender`, `zipcodeOri`,
`merchant`, `zipMerchant`, `category`, et `fraud` pour l'entraînement seulement.
Les neuf colonnes hors label sont utilisées. `step` et `amount` sont numériques ;
les sept autres sont encodées en one-hot, appris sur l'entraînement uniquement.
Le label `fraud` vaut 0 ou 1 et ne fait jamais partie des entrées du modèle.
Les catégories entourées d'apostrophes sont normalisées.

Les premiers 60 % des steps distincts servent à l'entraînement, les 20 % suivants
à la validation et les derniers 20 % au test, sans partager un step entre les partitions. L'encodage est appris
uniquement sur l'entraînement. Les métriques sont écrites dans
`artifacts/metrics.json` : précision, rappel et average precision (résumé de la
courbe précision-rappel, distinct de son intégrale trapézoïdale).
Le taux de fraude vérifié sur le CSV est de 1,2108 % (7 200 / 594 643).

## Validation et modèle actuel

La validation permet de choisir le seuil sans adapter ce choix aux résultats du
test. L'entraînement apprend les paramètres ; la validation règle le seuil ;
le test mesure ensuite le modèle et le seuil figés. L'ordre chronologique simule
la prédiction de transactions futures et évite de mélanger les mêmes steps.

| Partition | Steps | Transactions |
| --- | --- | --- |
| Entraînement | 0–107 | 332 592 |
| Validation | 108–143 | 128 820 |
| Test | 144–179 | 133 231 |

Le seuil maximise le F1 sur la validation (moyenne harmonique de précision et
rappel). C'est un compromis initial, pas un coût métier optimal. En cas d'égalité
exacte, le seuil le plus élevé est retenu. Le modèle n'est pas réentraîné après
ce choix afin de préserver l'échelle des scores utilisée pour choisir le seuil.
`--threshold 0.5` permet toujours un seuil fixe explicite.

Seuil sélectionné : **0,456131**. F1 validation : **0,8267**.
Les champs de métriques à la racine de `artifacts/metrics.json` concernent le test ;
`validation` et `test_at_threshold_0_5` contiennent les résultats complémentaires.

| Test, même modèle | Seuil 0,5 | Seuil validé 0,456131 |
| --- | --- | --- |
| Précision | 93,25 % | 91,82 % |
| Rappel | 71,04 % | 73,26 % |
| F1 | 0,8065 | 0,8150 |
| Fraudes détectées / manquées | 1 023 / 417 | 1 055 / 385 |
| Fausses alertes | 74 | 94 |

Average precision : 0,9128 pour les deux seuils (elle dépend des scores, pas du
seuil choisi). Les anciennes versions ont appris sur plus de données ; comparer
leurs résultats au modèle actuel ne mesure donc pas uniquement l'effet du seuil.
Le test a déjà été consulté lors des expériences précédentes : ces résultats
restent exploratoires. Une évaluation finale aveugle nécessite de nouvelles
données jamais utilisées pour guider les décisions.

## Historique : comparaison des features avant validation

Aucune cellule vide ni ligne entièrement dupliquée. Les modalités `U` existent
et sont conservées comme catégories ; absence de cellules vides ne signifie
donc pas absence d'informations inconnues. Le fichier couvre 180 steps (0–179).
Le rapport détaillé est dans `artifacts/data_report.json`, avec empreinte SHA-256.

Entraînement : 461 412 transactions des steps 0–143. Test : 133 231 transactions
des steps 144–179. Au seuil fixé à 0,5 :

| Mesure | Baseline 4 features | Ancien modèle 9 features |
| --- | --- | --- |
| Précision | 87,09 % | 93,62 % |
| Rappel | 63,26 % | 72,29 % |
| Average precision | 0,8034 | 0,9203 |
| Fraudes détectées / manquées | 911 / 529 | 1 041 / 399 |
| Fausses alertes | 135 | 71 |
| Transactions normales correctement classées | 131 656 | 131 720 |

L'ancien modèle et ses métriques sont conservés dans `artifacts/baseline_4_features`.
Les paramètres, le seuil et la séparation chronologique sont identiques.
Le nouveau modèle manque environ 28 % des fraudes. Cette comparaison réutilise
le test déjà consulté : il ne s'agit plus d'une évaluation finale aveugle.
La version 9 features sans validation est archivée dans `artifacts/baseline_9_features`.
Les identifiants peuvent aider sur des clients déjà connus ; ces résultats ne
mesurent pas séparément les performances sur de nouveaux clients ou commerçants.
Les codes postaux constants n'apportent pas de discrimination et `step` ne permet
pas aux arbres d'extrapoler une tendance temporelle au-delà de l'entraînement.
Ces résultats sur BankSim synthétique ne démontrent pas les performances réelles.
L'exemple JSON contient maintenant les neuf features ; son label n'est pas connu.

Vérification locale : `python -m unittest discover -s tests -v` (7 tests réussis :
exclusion du label, conservation des identifiants, montants/steps invalides,
catégories et identifiants inconnus, séparation chronologique, sélection du seuil
et rejet d'un nombre insuffisant de steps).
Utiliser le Python de `.venv` pour cette commande.

Le seuil choisi sur validation est enregistré avec le modèle et utilisé par
`predict.py`. Le score n'est pas
une probabilité calibrée garantie ; une alerte indique un cas à examiner.
L'exemple JSON est fictif et ne garantit aucun score particulier.
Ne charger que des fichiers joblib de confiance.

## Étapes suivantes

1. Analyser les documents du brief et confirmer les exigences.
2. Définir le coût des fraudes manquées et des fausses alertes pour les prochains choix sur validation.
3. Connecter le rejeu BankSim local existant au futur producteur Kinesis.
4. Implémenter Kinesis, Lambda, SageMaker et DynamoDB avec Terraform.
5. Déployer Streamlit sur ECS Fargate ; ajouter OIDC GitHub/AWS et CloudWatch.

## Publication GitHub

Le dépôt privé est disponible sur https://github.com/balsem2/FraudFlow.
Pour récupérer le projet avec un compte autorisé :

```powershell
git clone https://github.com/balsem2/FraudFlow.git
cd FraudFlow
```

Les données, modèles et secrets sont exclus du versionnement. La CI vérifie
compilation, imports et contrats du modèle, sans évaluer BankSim ni déployer AWS.
`requirements-lock.txt` conserve les versions validées localement ;
`requirements.txt` décrit les plages autorisées pour les futures mises à jour.

## Références techniques

- [OneHotEncoder, scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html)
- [API Python XGBoost](https://xgboost.readthedocs.io/en/stable/python/python_api.html)
