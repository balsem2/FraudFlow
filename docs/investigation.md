# Investigation après alerte — version locale et migration AWS

## Contrat de décision

Le pipeline XGBClassifier utilise 500 arbres (`fraudflow/model.py`). Il reçoit
uniquement les neuf features BankSim définies dans `FEATURES`. Il calcule le score
et compare ce score au seuil de l'artefact (`>=`, convention historique conservée).
Seules les transactions signalées sont transmises au `FraudInvestigationAgent`.
L'agent, dans `fraudflow/investigation.py`, n'importe pas Streamlit. Son résultat
ne contient pas de nouvelle décision, de nouveau score ou de nouveau seuil.
Les échecs d'investigation ne suppriment jamais l'alerte XGBoost.

L'artefact local existant a été vérifié : XGBClassifier, 500 arbres. Le seuil
actuel vient de son entraînement/validation ; il n'est jamais remplacé par 0,5
dans le chemin de décision. Pour entraîner un nouvel artefact :

```powershell
.\.venv\Scripts\python.exe -m fraudflow.train --data data/banksim.csv
```

## Indicateurs et hypothèses

L'agent filtre l'historique sur le même client et sur les événements strictement
antérieurs. Il calcule le montant moyen client, la moyenne client/commerçant,
le ratio montant/moyenne, les compteurs de transactions et les scores de risque
historiques moyens. Le taux historique de scores >= 0,5 est un indicateur descriptif,
pas un taux de fraude confirmé ni le seuil décisionnel du modèle.

Les règles initiales, versionnées `investigation-v3`, proposent :

| Code | Indice observé |
| --- | --- |
| unusual_amount | Montant >= 3 fois la moyenne disponible |
| new_merchant | Commerçant absent de l'historique client connu |
| high_velocity | Au moins 5 transactions antérieures dans la dernière heure |
| new_category | Catégorie absente de l'historique connu |
| unknown_device | Appareil absent des appareils précédemment observés |
| unknown_ip | IP absente des IP précédemment observées |
| geographic_anomaly | Pays différent des pays précédemment observés |
| account_takeover | Au moins 3 échecs d'authentification avec appareil nouveau et IP ou pays nouveau |

La nouveauté signifie **absent de l'historique fourni**, pas nouveau à l'échelle
de la banque. Le pays nouveau n'est pas une mesure d'impossible travel. La prise
de contrôle reste une hypothèse, jamais une preuve. Un historique manquant produit
des valeurs inconnues et éventuellement une cause indéterminée, pas des anomalies
inventées. Pour le CSV BankSim seul, l'historique SQLite contient au maximum 100
analyses antérieures du même client (steps strictement plus petits). Il ne contient
pas nécessairement toute sa vie bancaire. Pas de vitesse subjournalière déduite
du champ step. Le contexte lie utilise tous les jours anterieurs disponibles.

Les cinq premières importances globales XGBoost sont agrégées par variable après
one-hot encoding. Elles sont affichées séparément des indicateurs historiques.
**Ce ne sont pas des contributions locales SHAP ni des explications causales.**
Les nouvelles variables de sécurité ne sont pas apprises par le détecteur actuel :
une transaction à faible score XGBoost avec un appareil suspect ne déclenchera donc
pas cet agent. C'est une limite volontaire du déclenchement exclusivement après alerte.

## Dataset complémentaire et absence de fuite

```powershell
.\.venv\Scripts\python.exe -m fraudflow.synthetic_investigation --rows 5000 --seed 42
.\.venv\Scripts\python.exe -m fraudflow.evaluate_investigation
```

Le generateur v3 produit les identifiants, le JSONL lie, le CSV d'indicateurs
et le manifeste de provenance dans data/. Le fichier BankSim reste intact.
ID = SHA-256 du fichier source + ligne (base zero, hors header). Il reste stable
pour une source identique. Selection de 5000 lignes sans remplacement (steps >=144).

Les montants, clients, merchants et categories de l'historique viennent de BankSim.
Les heures manquantes sont simulees uniformement dans chaque jour, de facon
reproductible, puis triees. L'historique contient uniquement les evenements
strictement anterieurs du client selon CETTE chronologie simulee. La vitesse sur
une heure est maintenant calculable mais n'est PAS une observation reelle BankSim.
Les jours restent ceux du dataset ; aucun paiement supplementaire n'est fabrique.
La distribution simulee ne garantit pas des exemples de forte vitesse.

Appareils, IP, pays et authentification restent simules avec continuite par client.
Les labels de scenarios sont attribues au moment des injections, sans appeler les
regles de detection : unknown_device, unknown_ip, geographic_anomaly, account_takeover.
Le retour a un pays deja connu peut ne pas etre detecte, et une attaque injectee peut
avoir trop peu d'echecs pour declencher une hypothese : ce sont des ecarts mesurables.
Ces labels ne sont ni des fraudes reelles confirmees ni les causes du score XGBoost.
Montant inhabituel, nouveau merchant/categorie et vitesse sont des indices sans
labels independants ; ils sont exclus des metriques de causes.
fraud n'est pas lu. Labels, contexte et identifiants sont exclus des features XGBoost.

Le formulaire permet de choisir un numero de transaction liee et de l'analyser
avec exactement le meme contexte que le replay, sans modifier ses champs.
La saisie libre utilise l'historique local disponible sans fabriquer de contexte.
Les anciens resultats v1/v2 ne sont pas comparables aux metriques v3.

## Dashboard et replay sans AWS

Dans « Historique et statistiques », sélectionner « BankSim + contexte synthétique »
et démarrer le replay après génération du dataset. Les colonnes cause et confiance
et le détail d'investigation montrent les indicateurs, facteurs globaux, explication
et recommandation. Aucun appel LLM n'est effectué en consultant une ancienne enquête.
Les anciennes lignes SQLite sans investigation restent lisibles.

Producteur indépendant :

```powershell
.\.venv\Scripts\python.exe -m fraudflow.producer --data data/investigation_synthetic.jsonl --run-id investigation-v3 --batch-size 25 --max-batches 2
```

Dans Docker, les fichiers du répertoire `data` sont montés en lecture seule pour
le producteur ; le mode mock est explicite dans Compose :

```powershell
docker compose run --rm producer python -m fraudflow.producer --data /data/investigation_synthetic.jsonl --run-id investigation-docker-v3
```

La signature du checkpoint inclut désormais la version d'investigation et le mode
LLM. Après migration depuis l'ancien producteur, utiliser un **nouveau run-id** ;
les anciennes prédictions et positions sont conservées. Un retry après crash peut
répéter un appel LLM avant le commit, même si les prédictions SQLite ne sont pas
dupliquées. En production, découpler l'investigation et utiliser une clé d'idempotence.

## Mock et Bedrock

Le mode par défaut est `mock` : un simulateur déterministe de réponse LLM,
pas un modèle de langage entraîné. Aucune clé, aucun réseau, aucune facturation.
Les règles proposent des causes ; le LLM les sélectionne et les explique avec
une confiance qualitative faible/modérée, **non calibrée**. Une absence d'indices
impose une confiance faible. Les recommandations n'exécutent aucune action.

L'adaptateur Bedrock utilise l'API Converse et un modèle compatible choisi par
l'opérateur. Aucun modèle payant n'est appelé pendant les tests locaux.

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements-aws.txt
$env:FRAUDFLOW_LLM_MODE = 'bedrock'
$env:FRAUDFLOW_BEDROCK_MODEL_ID = '<identifiant ou profil autorisé>'
$env:AWS_REGION = '<région autorisée>'
```

L'authentification utilise la chaîne standard AWS (rôle en production, session
temporaire Academy en développement), jamais des clés dans le code. Installer
aussi `requirements-aws.txt` dans l'image de production et verrouiller les versions
validées. Le Dockerfile local reste sans dépendance AWS obligatoire.
Lire [Converse, documentation Boto3](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html).

Timeouts bornés, nombre de retries limité, validation JSON stricte des causes,
confiance et actions. Une réponse hors schéma ou une panne produit un résultat
`degraded` / `mock_fallback` ; les exceptions fournisseur brutes ne sont pas conservées.
Le corps libre du LLM est affiché comme texte et toujours précédé de « Cause probable ».
Il reste à évaluer sémantiquement ces explications avec des analystes avant production.

## Confidentialité

Seule une liste autorisée d'agrégats numériques/booléens, de codes de causes et de
noms de features est envoyée à Bedrock. Aucun identifiant client/commerçant brut,
appareil, IP, localisation précise, historique brut ou label n'est envoyé.
Les contextes bruts ne sont pas enregistrés dans SQLite ni exportés par le dashboard.
Les identifiants BankSim déjà utilisés par l'application restent dans l'historique
local ; ils sont simulés. Pour des données réelles, appliquer pseudonymisation,
authentification, contrôle d'accès, chiffrement et durée de rétention avant ingestion.
Pas de prompt contenant des commentaires libres d'utilisateurs, pas d'outil LLM
permettant de bloquer un compte ou d'exécuter du code. Ne jamais charger un artefact
joblib non fiable. Les datasets et artefacts sont exclus de Git/Docker build.

## Intégration AWS (code local, non déployé)

Le producteur, les deux handlers Lambda, les adaptateurs DynamoDB/SageMaker,
le chemin Bedrock et les ressources IAM/CloudWatch/ECS/Kinesis/SQS/DynamoDB/
SageMaker sont implémentés dans le dépôt. Terraform empaquette les handlers,
charge le modèle préparé dans S3 et fournit des options de désactivation pour les
services facturables. Voir [le guide Terraform](../infra/terraform/README.md)
pour la séquence de construction et les validations restantes.

Ce code n'a pas encore été exécuté dans AWS. Les permissions Academy/LabRole,
les quotas, la région et l'accès Bedrock doivent être confirmés. Le dashboard
ECS est une démo HTTP sans authentification/TLS ; sa règle réseau doit être
restreinte à une adresse publique `/32`. Aucun `terraform apply`, push ECR ou
appel Bedrock réel n'a été effectué.

Le budget Academy et l'accès Bedrock doivent être confirmés avant tout déploiement.

Resultats du contexte lie v3 : `reports/investigation_linked_v3.md`.

## Verification du vrai LLM

Le SDK optionnel s'installe avec `uv pip install --python .venv/Scripts/python.exe -r requirements-aws.txt`.
Configurer les credentials temporaires AWS Academy hors du depot (profil AWS local,
ou environnement local, avec le session token). Ne jamais les coller dans le chat.
Configurer AWS_REGION et FRAUDFLOW_BEDROCK_MODEL_ID avec un modele accessible.

```powershell
.\.venv\Scripts\python.exe -m fraudflow.check_bedrock
# Un appel reel, potentiellement facture, sur la transaction signalee 66 :
.\.venv\Scripts\python.exe -m fraudflow.check_bedrock --invoke --index 66
```

Le premier controle verifie seulement la presence de configuration, sans appel LLM.
Le second ne reussit que si backend=bedrock et status=completed. Un mock_fallback
est un ECHEC de validation du vrai LLM. Ensuite, lancer le dashboard depuis le meme
terminal avec FRAUDFLOW_LLM_MODE=bedrock. Compose reste explicitement en mode mock.
