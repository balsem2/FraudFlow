# Producteur indépendant et Docker

Le producteur tourne sans Streamlit ni navigateur. Dans cette version locale,
il rejoue BankSim, appelle le modèle et écrit dans SQLite. Il n'envoie pas encore
vers Kinesis. Le dashboard lit la même base et se rafraîchit toutes les deux secondes.

## Exécution locale (PowerShell, racine du projet)

Terminal 1 — dashboard, sans simulation embarquée :

```powershell
$env:FRAUDFLOW_EXTERNAL_PRODUCER = '1'
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Terminal 2 — producteur :

```powershell
.\.venv\Scripts\python.exe -m fraudflow.producer --batch-size 25 --interval 2
```

Ctrl+C arrête le producteur après le lot en cours. Relancer la même commande
reprend sa position, même après fermeture du navigateur ou redémarrage du PC.
`--max-batches 2` limite un essai à deux lots. Pour un nouveau rejeu complet,
choisir un nouveau `--run-id demo-2` : cela conserve les anciennes prédictions.
Ne lancer qu'un producteur par simulation en usage normal.

La table `producer_runs` conserve la position. Les prédictions et la position
sont validées dans une transaction SQLite unique ; un lot échoué est annulé.
Un contrôle de position protège aussi contre deux producteurs sur le même run.
L'empreinte SHA-256 du CSV et du modèle empêche une reprise silencieuse avec
des entrées différentes. Dans ce cas, un nouveau run-id est nécessaire.
Le modèle est chargé au démarrage : redémarrer le producteur pour changer de modèle.
Le rejeu utilise les steps >= 144 et s'arrête en fin de fichier, sans boucle infinie.

## Docker Compose

Prérequis : Docker Desktop démarré en mode conteneurs Linux, Compose v2,
`data/banksim.csv`, `data/investigation_synthetic.jsonl` et `artifacts/model.joblib` presents.
Pour verifier build, sante HTTP, reprise, absence de doublons et persistance :

```powershell
.\.venv\Scripts\python.exe scripts/validate_docker.py
```

Le script utilise un projet Compose temporaire isole et nettoie uniquement son volume.
Il conserve l'image construite. Le dossier data est partage en lecture seule.
Pour choisir un autre port : `$env:FRAUDFLOW_PORT = '8502'`.

Arrêter le Streamlit local avant d'utiliser le même port 8501 dans Docker.

```powershell
docker compose config --quiet
docker compose build
docker compose up -d dashboard
docker compose --profile simulation up -d producer
docker compose logs -f producer
```

Ouvrir http://localhost:8501. Fermer le navigateur n'arrête pas le producteur.
Ctrl+C pendant `logs -f` ferme seulement l'affichage des logs.

```powershell
# Arrêter puis reprendre le producteur
docker compose stop producer
docker compose --profile simulation up -d producer
# Arrêter les deux services, conserver l'historique et la position
docker compose --profile simulation down
```

Le volume nommé `state` persiste après `down`. **Ne pas ajouter `--volumes` / `-v`**
si l'historique doit être conservé. L'historique Docker est distinct du fichier
SQLite local existant. Le modèle et le CSV sont montés en lecture seule, sans
être copiés dans l'image. Aucun secret ni dataset n'entre dans le contexte du build.
L'image exécute les services avec un utilisateur non-root et les versions verrouillées.

Pour un essai borné (producteur habituel arrêté) :

```powershell
docker compose run --rm producer python -m fraudflow.producer --run-id essai-docker --max-batches 2
```

Les deux services partagent SQLite sur un seul hôte Docker. Ce montage est destiné
au développement local, pas au stockage distribué sur ECS. Pour AWS, le producteur
publiera sur Kinesis, Lambda/SageMaker traiteront le flux et DynamoDB stockera les résultats.

Référence : [services Compose](https://docs.docker.com/reference/compose-file/services/)
et [profils optionnels](https://docs.docker.com/compose/how-tos/profiles/).
