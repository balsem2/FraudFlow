# Comparaison des modèles — 6 novembre 2026

La régression logistique obtient la meilleure average precision sur cette
validation : 0,9055 contre 0,9022 pour XGBoost. L'écart de 0,0033 est faible ;
aucune supériorité statistique ou générale n'est démontrée.

## Protocole

- Même CSV BankSim et mêmes neuf features, sans le label fraud en entrée.
- Entraînement : steps 0–107, 332 592 transactions.
- Validation : steps 108–143, 128 820 transactions, dont 1 440 fraudes.
- Aucun calcul sur le test dans cette expérience ; il avait déjà été consulté auparavant.
- One-hot appris sur le train uniquement ; standardisation numérique pour la régression logistique.
- Trois configurations fixes, sans recherche d'hyperparamètres ni pondération des classes.
- Seuil de chaque modèle choisi en maximisant le F1 de validation.
- Critère de classement fixé avant l'expérience : average precision de validation.

## Résultats de validation

| Modèle | Average precision | Précision | Rappel | F1 | Accuracy | Entraînement |
| --- | --- | --- | --- | --- | --- | --- |
| Régression logistique | **0,9055** | 88,66 % | **77,64 %** | **82,78 %** | 99,639 % | 2,00 s |
| XGBoost | 0,9022 | **90,36 %** | 76,18 % | 82,67 % | **99,643 %** | 4,97 s |
| Random Forest | 0,8552 | 85,42 % | 75,28 % | 80,03 % | 99,580 % | 16,78 s |

| Modèle | Seuil | Fraudes détectées | Fraudes manquées | Fausses alertes |
| --- | --- | --- | --- | --- |
| Régression logistique | 0,434674 | 1 118 | 322 | 143 |
| XGBoost | 0,456131 | 1 097 | 343 | 117 |
| Random Forest | 0,188222 | 1 084 | 356 | 185 |

La régression logistique détecte 21 fraudes de plus que XGBoost, avec 26 fausses
alertes supplémentaires. Ces seuils n'imposent pas la même précision minimale.
Les temps sont des mesures uniques sur ce poste, incluant le prétraitement ;
ce ne sont pas des benchmarks AWS.

## Paramètres et limites

Régression logistique : lbfgs, C=1, max_iter=2000 ; convergence atteinte.
Random Forest : 200 arbres, profondeur 16, min_samples_leaf=2, max_features=sqrt,
2 threads et random_state=42. XGBoost conserve ses paramètres actuels :
200 arbres, profondeur 4, learning_rate=0,08, hist, 2 threads, random_state=42.

Il s'agit d'une comparaison de configurations, pas d'une optimisation exhaustive
des trois familles. La validation sert à sélectionner les seuils et le candidat ;
ses métriques ne constituent donc pas une estimation indépendante finale.
La généralisation à de nouveaux clients et à des données réelles reste à étudier.
Une comparaison sur plusieurs fenêtres chronologiques et à contrainte de précision
commune serait utile avant de décider d'un remplacement en production.

Le modèle actif du dashboard reste XGBoost. Les trois modèles et les résultats
détaillés sont enregistrés séparément dans `artifacts/comparison/`.

## Reproduire

```powershell
.\.venv\Scripts\python.exe -m fraudflow.compare
```

Le script produit `artifacts/comparison/results.json` avec l'empreinte du dataset,
les paramètres, les temps, les métriques et le gagnant. Les dix tests existants
ont également été exécutés avec succès après l'ajout du comparateur.
