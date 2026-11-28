# FraudFlow

Projet pédagogique de détection de transactions suspectes combinant AWS,
Machine Learning et MLOps.

## État du projet

Première baseline exécutée localement le 5 novembre 2026 : analyse BankSim,
entraînement XGBoost, évaluation chronologique et prédiction JSON fonctionnent.
Le modèle local est dans `artifacts/model.joblib` (non versionné).
Le dashboard Streamlit local est disponible. Les handlers AWS, adaptateurs,
producteur Kinesis et configuration Terraform sont écrits, mais restent à valider
et à déployer dans un compte autorisé. Aucun `terraform apply` ni ressource AWS
n'a été exécuté depuis ce dépôt.

## Architecture cible

BankSim → producteur Kinesis → Lambda de détection → endpoint SageMaker
(prétraitement + XGBoost) → DynamoDB → dashboard Streamlit sur ECS/Fargate.
Les alertes passent par SQS FIFO vers une Lambda d'investigation Bedrock et une
DLQ. Les ressources et rôles sont décrits dans `infra/terraform`.

Le guide [Terraform AWS](infra/terraform/README.md) décrit la validation locale,
la livraison des images à ECR, le dépôt du modèle dans S3 et l'ordre prudent
d'activation. SageMaker, le consommateur Bedrock et le service ECS sont opt-in ;
les permissions Academy, l'accès Bedrock et les coûts doivent être vérifiés avant
toute application. L'accès ECS actuel est une démo HTTP restreinte par CIDR,
pas un déploiement de production.

## Dashboard local

Une **investigation après alerte XGBoost (500 arbres)** est maintenant disponible :
indicateurs historiques, causes probables, importances globales et explication
mock locale, avec adaptateur Bedrock optionnel. Voir le
[guide d'investigation et migration AWS](docs/investigation.md) pour générer le
dataset synthétique multilabel, lancer l'évaluation et utiliser le replay.
L'investigation ne modifie jamais le score, le seuil ou la décision du détecteur.

Le **producteur indépendant avec reprise persistante** et les fichiers Docker
sont décrits dans [le guide producteur et Docker](docs/producer-docker.md).
Le producteur fonctionne sans navigateur. Docker Compose prévoit un dashboard
et un producteur optionnel partageant un volume SQLite. Le profil `inference`
ajoute un service local distinct pour tester le contrat SageMaker ; il n'est pas
encore appelé par le dashboard.

Une image d'inférence compatible SageMaker peut être construite et testée
localement avec Docker ; voir le [guide d'inférence](docs/sagemaker-inference.md).
Elle ne déploie aucune ressource AWS.

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

`fraudflow/dashboard_service.py` conserve les adaptateurs locaux ; lorsque
`FRAUDFLOW_BACKEND=aws`, le dashboard utilise SageMaker et DynamoDB via
`fraudflow/aws_adapters.py`. L'image `Dockerfile.aws` inclut les dépendances AWS,
alors que l'image Docker locale garde son mode SQLite. SQLite n'est pas le
stockage du service Fargate. Aucune ressource AWS n'est déployée et l'application
n'inclut pas d'authentification.

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

Seuil sélectionné : **0,340403**. F1 validation : **0,8464**.
Les champs de métriques à la racine de `artifacts/metrics.json` concernent le test ;
`validation` et `test_at_threshold_0_5` contiennent les résultats complémentaires.

| Test, même modèle | Seuil 0,5 | Seuil validé 0,340403 |
| --- | --- | --- |
| Précision | 92,68 % | 89,99 % |
| Rappel | 73,89 % | 78,68 % |
| F1 | 0,8223 | 0,8396 |
| Fraudes détectées / manquées | 1 064 / 376 | 1 133 / 307 |
| Fausses alertes | 84 | 126 |

Average precision : 0,9270 pour les deux seuils (elle dépend des scores, pas du
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

## État AWS / étapes restantes

1. Lancer les validations locales du guide Terraform et examiner les diagnostics.
2. Confirmer les permissions du compte Academy, l'accès au modèle Bedrock et les quotas.
3. Créer les ressources seulement après examen du plan et du coût ; le déploiement
   ECS HTTP est limité à une adresse CIDR configurée et n'a ni TLS ni authentification.
4. Construire/publier les images dans ECR et activer les services opt-in dans l'ordre
   indiqué dans le guide Terraform.
5. Ajouter plus tard un déploiement CI/CD (OIDC si autorisé), authentification HTTPS,
   alarmes notifiées et gestion distante/chiffrée de l'état Terraform.

## Publication GitHub

Le dépôt public est disponible sur https://github.com/balsem2/FraudFlow.
Pour récupérer le projet :

```powershell
git clone https://github.com/balsem2/FraudFlow.git
cd FraudFlow
```

Le CSV BankSim, les artefacts de modèle et les métriques publiés sont accompagnés
de leur attribution et soumis aux conditions CC BY-NC-SA 4.0 ; voir
`data/README.md`. Le JSONL synthétique d'investigation est fourni compressé.
Les historiques SQLite, secrets et autres fichiers locaux restent exclus du
versionnement. La CI vérifie compilation, imports et contrats du modèle, sans
évaluer BankSim ni déployer AWS.
`requirements-lock.txt` conserve les versions validées localement ;
`requirements.txt` décrit les plages autorisées pour les futures mises à jour.

## Références techniques

- [OneHotEncoder, scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html)
- [API Python XGBoost](https://xgboost.readthedocs.io/en/stable/python/python_api.html)
