# API d'ingestion de données

Un service FastAPI qui ingère des fichiers CSV et XLSX contenant des identités de personnes
vers une base de données relationnelle normalisée DuckDB. Il déduplique les enregistrements,
met à jour les personnes existantes lors d'un nouvel envoi, insère les nouveaux emplois et
conserve un historique des modifications champ par champ — le tout derrière un unique point
d'entrée `POST /upload`.

---

## Architecture

Le pipeline d'ingestion est linéaire :

```
POST /upload -> probe (FormatRegistry) -> parse (stratégie FormatHandler) -> upsert (repository) -> DuckDB
```

- **Strategy + Registry** — chaque format de fichier est une sous-classe de `FormatHandler`
  qui implémente `probe(filename, content)` (ce gestionnaire reconnaît-il le fichier ?) et
  `parse(content)` (transformer les octets en enregistrements canoniques). `FormatRegistry`
  détient les gestionnaires et renvoie le premier qui accepte un fichier. Ajouter un format
  revient à ajouter une classe et une ligne d'enregistrement.
- **Modèle canonique** — chaque parseur converge vers le même modèle Pydantic `IngestedRecord`
  (`person` + `organization` + `job`). Le schéma de base de données et le repository ne voient
  que cette unique forme, quel que soit le nombre de formats sources.
- **Stockage normalisé** — trois tables (`person`, `job`, `organization`) plus une table d'audit
  `person_history` en ajout seul. La déduplication est assurée par des index uniques utilisant
  des `''` / `-1` au lieu de `NULL` (voir `IMPLEMENTATION_PLAN.md` §3.3).

## Stack technique

- **FastAPI** — API HTTP, envois multipart, documentation OpenAPI.
- **Pydantic v2** — validation des enregistrements canoniques et modèles de réponse.
- **DuckDB** — base de données relationnelle embarquée mono-fichier.
- **pandas** — parsing CSV / XLSX.
- **Docker** — packaging et exécution reproductibles.

## Structure du projet

```
app/
  main.py            # factory d'application FastAPI + lifespan (initialisation de la base)
  config.py          # configuration (variable d'environnement DUCKDB_PATH)
  db.py              # connexion DuckDB + bootstrap du schéma
  models/            # Pydantic : record.py (canonique), responses.py (UploadSummary)
  schemas/schema.sql # DDL (person, job, organization, person_history)
  api/routes/        # health.py, upload.py
  parsers/           # Strategy + Registry
    base.py          # ABC FormatHandler (probe + parse) + erreurs
    registry.py      # FormatRegistry
    formats/         # un fichier par format
      csv_format_1.py
      xlsx_format_1.py
  services/
    ingest.py        # orchestration probe -> parse -> upsert
    repository.py    # SQL d'upsert/déduplication/mise à jour
    history.py       # diff des champs + écritures d'historique
tests/
data/                # fichiers d'entrée fournis
Dockerfile
docker-compose.yml
requirements.txt
pyproject.toml
```

## Prérequis

- Docker avec le plugin Compose (`docker compose`).

## Lancer avec Docker

```bash
docker compose up --build
```

- API : `http://localhost:8000`
- Documentation interactive : `http://localhost:8000/docs`

Le fichier DuckDB est monté en bind depuis le dossier hôte `./data_db` , de sorte que les données survivent aux redémarrages du conteneur et soient
directement inspectables sur l'hôte.

## Points d'entrée de l'API

| Méthode | Chemin     | Entrée                        | Succès                          | Erreurs |
|---------|------------|-------------------------------|---------------------------------|---------|
| `GET`   | `/health`  | —                             | `200 {"status":"ok"}`           | — |
| `POST`  | `/upload`  | champ de formulaire multipart `file` | `200` + `UploadSummary`   | `400` fichier manquant/vide, `415` format non pris en charge, `422` erreur de parse/validation |

`UploadSummary` :

```json
{
  "format": "csv_format_1",
  "persons_created": 0,
  "persons_updated": 0,
  "jobs_created": 0,
  "organizations_created": 0,
  "history_rows_written": 0
}
```

## Reproduire le cas d'usage

Envoyez les quatre fichiers fournis dans l'ordre :

```bash
curl -F "file=@data/data_1.csv"  http://localhost:8000/upload
# {"format":"csv_format_1","persons_created":16,"persons_updated":0,"jobs_created":16,"organizations_created":1,"history_rows_written":0}

curl -F "file=@data/data_2.xlsx" http://localhost:8000/upload
# {"format":"xlsx_format_1","persons_created":24,"persons_updated":0,"jobs_created":24,"organizations_created":1,"history_rows_written":0}

curl -F "file=@data/data_3.xlsx" http://localhost:8000/upload
# {"format":"xlsx_format_1","persons_created":0,"persons_updated":8,"jobs_created":10,"organizations_created":2,"history_rows_written":14}

curl -F "file=@data/data_4.xlsx" http://localhost:8000/upload
# {"format":"xlsx_format_1","persons_created":0,"persons_updated":4,"jobs_created":5,"organizations_created":0,"history_rows_written":9}
```

`data_1.csv` + `data_2.xlsx` chargent les 40 personnes du *tronc commun*. `data_3.xlsx` +
`data_4.xlsx` mettent ensuite à jour les coordonnées des personnes existantes et insèrent de
nouveaux emplois (*subsidiaire*), pour aboutir à **40 personnes / 4 organisations / 55 emplois /
23 lignes d'historique** — aucune personne en double n'est jamais créée.

## Inspecter la base de données

DuckDB ne supporte pas de concurrence en écriture : tant que l'API est en cours d'exécution, elle détient la seule
connexion ouverte, de sorte qu'un autre processus ne peut pas ouvrir le fichier (même en lecture
seule). Pour l'inspecter, arrêtez l'API, puis interrogez le fichier sur l'hôte :

```bash
docker compose stop api
.venv/bin/python -c "import duckdb; c=duckdb.connect('data_db/app.duckdb', read_only=True); print(c.execute('SELECT count(*) FROM person').fetchone())"
docker compose start api
```

(N'importe quel client DuckDB fonctionne : la CLI DuckDB, le venv du projet, ou DBeaver.)

## Lancer les tests

En local (un venv dans `.venv/` avec `requirements.txt` installé) :

```bash
.venv/bin/python -m pytest
```

Dans le conteneur :

```bash
docker compose run --rm api pytest
```

## Ajouter un nouveau format

1. Créez `app/parsers/formats/<ext>_format_N.py` avec une sous-classe de `FormatHandler`
   implémentant `probe` et `parse`.
2. Enregistrez-la dans `build_default_registry()` dans `app/parsers/__init__.py`.
3. Ajoutez un test dans `tests/test_formats.py`.

Aucune modification de l'API, du repository ou du schéma de base de données n'est nécessaire.

## Historisation

Les modifications sont enregistrées dans une table d'audit `person_history` en ajout seul : une
ligne par champ modifié, avec l'ancienne valeur, la nouvelle valeur, un compteur `version` par
personne et le fichier source. La règle de priorité est **la dernière valeur ingérée l'emporte**,
de sorte qu'un fichier corrigé peut simplement être renvoyé pour écraser une valeur antérieure.
Voir `IMPLEMENTATION_PLAN.md` §7 pour la justification complète et les alternatives envisagées.
