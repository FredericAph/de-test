# Data Ingestion API

A FastAPI service that ingests CSV and XLSX files of people identities into a normalized
DuckDB relational database. It deduplicates records, updates existing persons on re-upload,
inserts new jobs, and keeps a field-level change history — all behind a single `POST /upload`
endpoint.

---

## Architecture

The ingest pipeline is a straight line:

```
POST /upload -> probe (FormatRegistry) -> parse (FormatHandler strategy) -> upsert (repository) -> DuckDB
```

- **Strategy + Registry** — each file format is a `FormatHandler` subclass implementing
  `probe(filename, content)` (does this handler recognize the file?) and `parse(content)`
  (turn bytes into canonical records). `FormatRegistry` holds the handlers and returns the first
  one that accepts a file. Adding a format means adding one class and one registration line.
- **Canonical model** — every parser converges on the same Pydantic `IngestedRecord`
  (`person` + `organization` + `job`). The database schema and the repository only ever see this
  one shape, regardless of how many source formats exist.
- **Normalized storage** — three tables (`person`, `job`, `organization`) plus an append-only
  `person_history` audit table. Dedup is enforced by unique indexes using `''` / `-1` sentinels
  instead of `NULL` (see `IMPLEMENTATION_PLAN.md` §3.3).

## Tech stack

- **FastAPI** — HTTP API, multipart uploads, OpenAPI docs.
- **Pydantic v2** — canonical record validation and response models.
- **DuckDB** — embedded single-file relational database.
- **pandas** — CSV / XLSX parsing.
- **Docker** — reproducible packaging and runtime.

## Project structure

```
app/
  main.py            # FastAPI app factory + lifespan (DB init)
  config.py          # settings (DUCKDB_PATH env var)
  db.py              # DuckDB connection + schema bootstrap
  models/            # Pydantic: record.py (canonical), responses.py (UploadSummary)
  schemas/schema.sql # DDL (person, job, organization, person_history)
  api/routes/        # health.py, upload.py
  parsers/           # Strategy + Registry
    base.py          # FormatHandler ABC (probe + parse) + errors
    registry.py      # FormatRegistry
    formats/         # one file per format
      csv_format_1.py
      xlsx_format_1.py
  services/
    ingest.py        # probe -> parse -> upsert orchestration
    repository.py    # upsert/dedup/update SQL
    history.py       # field diff + history writes
tests/
data/                # provided input files
Dockerfile
docker-compose.yml
requirements.txt
pyproject.toml
```

## Prerequisites

- Docker with the Compose plugin (`docker compose`).

## Run with Docker

```bash
docker compose up --build
```

- API: `http://localhost:8000`
- Interactive docs: `http://localhost:8000/docs`

The DuckDB file is bind-mounted from the host folder `./data_db` (create it first with
`mkdir -p data_db`), so data survives container restarts and is directly inspectable on the host.

## API endpoints

| Method | Path      | Input                          | Success                          | Errors |
|--------|-----------|--------------------------------|----------------------------------|--------|
| `GET`  | `/health` | —                              | `200 {"status":"ok"}`            | — |
| `POST` | `/upload` | multipart form field `file`    | `200` + `UploadSummary`          | `400` missing/empty file, `415` unsupported format, `422` parse/validation error |

`UploadSummary`:

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

## Reproducing the use-case

Upload the four provided files in order:

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

`data_1.csv` + `data_2.xlsx` load the 40 persons of the *tronc commun*. `data_3.xlsx` +
`data_4.xlsx` then update existing persons' contact details and insert new jobs (*subsidiaire*),
ending at **40 persons / 4 organizations / 55 jobs / 23 history rows** — no duplicate persons are
ever created.

## Inspecting the database

DuckDB is single-writer: while the API is running it holds the only open connection, so another
process cannot open the file (even read-only). To inspect it, stop the API, then query the file on the host:

```bash
docker compose stop api
.venv/bin/python -c "import duckdb; c=duckdb.connect('data_db/app.duckdb', read_only=True); print(c.execute('SELECT count(*) FROM person').fetchone())"
docker compose start api
```

(Any DuckDB client works: the DuckDB CLI, the project venv, or DBeaver.)

## Running tests

Locally (a venv at `.venv/` with `requirements.txt` installed):

```bash
.venv/bin/python -m pytest
```

In the container:

```bash
docker compose run --rm api pytest
```

## Adding a new format

1. Create `app/parsers/formats/<ext>_format_N.py` with a `FormatHandler` subclass implementing
   `probe` and `parse`.
2. Register it in `build_default_registry()` in `app/parsers/__init__.py`.
3. Add a test in `tests/test_formats.py`.

No changes to the API, the repository, or the database schema are required.

## Historisation

Changes are recorded in an append-only `person_history` audit table: one row per changed field,
with the old value, new value, a per-person `version` counter, and the source file. The priority
rule is **latest ingested value wins**, so a corrected file can simply be re-uploaded to overwrite
a previous value. See `IMPLEMENTATION_PLAN.md` §7 for the full rationale and alternatives
considered.
