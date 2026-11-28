# Image d'inférence compatible SageMaker

Cette image locale sert uniquement le score de fraude. Elle réutilise le pipeline
et le seuil de `artifacts/model.joblib` ; elle n'appelle ni Bedrock, ni DynamoDB,
et ne crée aucune ressource AWS.

## Construire et lancer en local

Prérequis : Docker Desktop en mode conteneurs Linux et le fichier
`artifacts/model.joblib`.

```powershell
docker compose --profile inference up -d --build inference
```

Le service écoute sur `http://127.0.0.1:8082` par défaut. Vérifier la santé et
envoyer une transaction (ne pas inclure la colonne d'entraînement `fraud`) :

```powershell
Invoke-RestMethod http://127.0.0.1:8082/ping
$transaction = @{
    amount = 12.5; age = "'3'"; gender = "'F'"; step = 180
    customer = "customer-1"; merchant = "merchant-1"
    zipcodeOri = "28007"; zipMerchant = "28007"
    category = "'es_transportation'"; transaction_id = "demo-1"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
    -Uri http://127.0.0.1:8082/invocations `
    -ContentType application/json -Body $transaction
```

La réponse contient `risk_score`, `threshold`, `alert`, `model_version` et, si
fourni, `transaction_id`. Le code HTTP 400 signale un JSON ou des champs
invalides ; le champ `fraud` est refusé pour éviter de fournir la réponse cible
au modèle. Le profil Compose monte le modèle local en lecture seule et n'est
pas démarré par le `docker compose up` habituel.

Arrêter uniquement l'inférence :

```powershell
docker compose --profile inference stop inference
```

Pour changer le port local, définir `$env:FRAUDFLOW_INFERENCE_PORT = '8083'`
avant de lancer Compose.

## Préparer l'archive du modèle pour SageMaker

SageMaker extrait l'archive S3 sous `/opt/ml/model`. Générer une archive
contenant `model.joblib` à sa racine :

```powershell
.\.venv\Scripts\python.exe scripts/package_sagemaker_model.py
```

Le résultat est `artifacts/sagemaker/model.tar.gz` (ignoré par Git). L'image
est construite par `Dockerfile.inference`, expose le port 8080 et implémente
`GET /ping`, `POST /ping` et `POST /invocations`. L'image et l'archive ne sont
pas publiées sur AWS par ces commandes.
