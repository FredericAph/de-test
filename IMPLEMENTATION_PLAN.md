# Implementation Plan — Data Ingestion API

> Technical test: build an API (FastAPI) that ingests CSV / XLSX files of people identities into a
> normalized relational database (DuckDB), packaged in Docker. The design must make it trivial to
> add new file formats, and must include a test suite.

---

## 1. Objective & scope

**Tronc commun (mandatory)**

- Expose `POST /upload` accepting `csv` and `xlsx` files containing people identities.
- Integrate their content into a relational database.
- Accept both provided example formats: `data_1.csv` and `data_2.xlsx`.
- Never insert duplicates twice (all-fields-identical deduplication).
- Create **3 normalized tables**: `person`, `job`, `organization`.

**Question subsidiaire (bonus)**

- `POST /upload` must **update existing persons** (uniquely identified by `first_name + middle_name + last_name`).
- After loading `data_1.csv` + `data_2.xlsx`, load `data_3.xlsx` + `data_4.xlsx` (same format as `data_2.xlsx`).
- **Insert the new jobs** and **update the persons' contact details** in `person`.

**Historisation**

- Keep a history of modified values; mechanism is our choice and must be justified.

---

## 2. Technology choices & rationale

| Concern | Choice | Rationale |
|---|---|---|
| Web framework | **FastAPI** | Async, typed, native Pydantic integration, auto OpenAPI docs, easy multipart uploads. |
| Data validation | **Pydantic v2** | Single source of truth for the canonical record and the DB schema; validation errors map cleanly to HTTP 422. |
| Database | **DuckDB** | Single-file, embedded, zero-ops relational DB; full SQL; ideal for a container; no external server. |
| File parsing (CSV & XLSX) | **pandas** | One library for all tabular formats: `read_csv` / `read_excel` are robust, well-known by the team, and reusable for future formats. Slightly heavier in memory, accepted for this use case. |
| Packaging | **Docker + docker-compose** | Reproducible env; single command to run. |
| Extensibility | **Strategy + Registry** | New format = one new parser class + one registration line; no change to API or DB. |
| Testing | **pytest + httpx (TestClient)** | Unit tests per layer + API tests incl. error paths. |

> **Why DuckDB over Postgres/SQLite**: DuckDB combines the simplicity of an embedded file DB
> (like SQLite) with an analytical/columnar engine and full modern SQL (window functions, upserts,
> CTEs). It ships a single-file embedded database (bind-mounted to the host, see §10) and removes
> the need to orchestrate a database service. It is a relational DB, satisfying the "base de
> données relationnelle au choix" requirement.

> **Concurrency trade-off**: DuckDB's native file format is single-process / single-writer (one
> process may hold the file open for writing; other processes are locked out while a writer is
> active). To keep the database independently queryable we: (1) persist it on the host via a bind
> mount (`./data_db`) and (2) parameterize its path with `DUCKDB_PATH`. For arbitrary external
> SQL, stop the API (releasing the lock) and point any DuckDB client at the file. See §10.5.

---

## 3. Data model & schema

### 3.1 Tables

```sql
-- sequences for surrogate keys (DuckDB INTEGER PRIMARY KEY is not auto-incrementing)
CREATE SEQUENCE IF NOT EXISTS person_seq;
CREATE SEQUENCE IF NOT EXISTS organization_seq;
CREATE SEQUENCE IF NOT EXISTS job_seq;
CREATE SEQUENCE IF NOT EXISTS person_history_seq;

-- organization (dimension, referenced by job)
CREATE TABLE IF NOT EXISTS organization (
    org_id        INTEGER PRIMARY KEY,
    org_name      TEXT    NOT NULL,
    org_vivo_uri  TEXT    NOT NULL DEFAULT ''    -- '' sentinel instead of NULL (see §3.3)
);

-- person (dedup key = first_name + middle_name + last_name)
CREATE TABLE IF NOT EXISTS person (
    person_id    INTEGER PRIMARY KEY,
    first_name   TEXT    NOT NULL,
    middle_name  TEXT    NOT NULL DEFAULT '',    -- '' sentinel instead of NULL (see §3.3)
    last_name    TEXT    NOT NULL,
    email        TEXT,
    phone        TEXT,
    fax          TEXT,
    title        TEXT
);

-- job (dedup key = person + org + title + type + start_date)
CREATE TABLE IF NOT EXISTS job (
    job_id      INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL,
    org_id      INTEGER NOT NULL,
    job_title   TEXT    NOT NULL,
    job_type    TEXT    NOT NULL DEFAULT '',     -- '' sentinel
    start_date  INTEGER NOT NULL DEFAULT -1      -- -1 sentinel (year; see §3.2)
);

-- history / audit log (justified in §7)
CREATE TABLE IF NOT EXISTS person_history (
    history_id   INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL,
    field_name   TEXT    NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    version      INTEGER NOT NULL,
    source_file  TEXT,
    changed_at   TIMESTAMP NOT NULL DEFAULT current_timestamp
);
```

Unique indexes enforcing dedup (plain indexes — no `NULL`s thanks to the sentinels):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_person_identity
    ON person (first_name, middle_name, last_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization
    ON organization (org_name, org_vivo_uri);

CREATE UNIQUE INDEX IF NOT EXISTS uq_job
    ON job (person_id, org_id, job_title, job_type, start_date);
```

> Schema lives in `app/schemas/schema.sql` and is applied idempotently at startup
> (see §9.4), so the container can start from an empty or a pre-copied DB file.

### 3.2 Field-level normalization rules (apply to every format)

- Trim all string fields (e.g. `data_1.csv` has `"Professor "` with a trailing space).
- `middle_name`, `org_vivo_uri`, `job_type`: `None`/`NaN`/empty → `''` (empty string).
- `start_date`: both sources give a **year** (`2001`, `2010`…); store as `INTEGER` year, with
  sentinel `-1` when absent (see §3.3). (If a future format provides a full date, the parser is
  responsible for normalizing it.)
- `email`, `phone`, `fax`, `title` may be absent → `NULL` (not used in any dedup index).
- Any cell that is empty in the source becomes `NULL` for `person` contact fields, and the
  sentinel (`''` / `-1`) for identity/dedup fields.

### 3.3 Why sentinels (`''` / `-1`) instead of `NULL` for dedup columns

Two independent reasons push us to store explicit sentinels (`''` for strings, `-1` for the
`start_date` year) rather than `NULL` in every column that participates in a dedup unique index:

1. **SQL `NULL` semantics**: `NULL` is distinct from `NULL`, so a unique index on
   `(first_name, middle_name, last_name)` would allow **two** rows with `middle_name = NULL`.
   A sentinel makes the uniqueness constraint actually enforce "one person per
   (first, middle, last) triple", as the test specifies.
2. **DuckDB upsert limitation** (verified during implementation): DuckDB's `INSERT … ON
   CONFLICT DO NOTHING` / `INSERT OR IGNORE` does **not** suppress conflicts on
   expression-based unique indexes (`COALESCE(col, '')`) when a `NULL` is involved — the second
   insert raises a `ConstraintException` instead of being ignored. Storing non-`NULL` sentinels
   lets us use plain unique indexes that the upsert correctly respects.

`email`, `phone`, `fax`, `title` and the history `old_value`/`new_value` columns are never part
of a dedup index, so they keep normal SQL `NULL` semantics for "absent".

---

## 4. Canonical record — the unique Pydantic schema

All parsers converge to **one** canonical model. This is what keeps the DB schema unique
regardless of how many source formats exist.

```python
# app/models/record.py
from pydantic import BaseModel, Field

class Person(BaseModel):
    person_id:   int | None = None      # filled by DB after insert
    first_name:  str
    middle_name: str = ""
    last_name:   str
    email:       str | None = None
    phone:       str | None = None
    fax:         str | None = None
    title:       str | None = None

class Organization(BaseModel):
    org_id:      int | None = None
    org_name:    str
    org_vivo_uri: str = ""

class Job(BaseModel):
    job_id:     int | None = None
    job_title:  str
    job_type:   str = ""
    start_date: int | None = None

class IngestedRecord(BaseModel):
    """One source row -> one normalized record."""
    person:       Person
    organization: Organization
    job:          Job
```

`IngestedRecord` is what the repository consumes and what unit tests assert on.

### 4.1 Column mapping (source → canonical)

| Canonical field | `data_1.csv` (semicolon) | `data_2/3/4.xlsx` (`raw_*`) |
|---|---|---|
| `person.first_name`  | `dataFirstNames` → part before `", "` | `raw_first` |
| `person.middle_name` | `dataFirstNames` → part after `", "` (else `''`) | `raw_middle` (NaN → `''`) |
| `person.last_name`   | `dataLastName` | `raw_last` |
| `person.email`       | `dataEmail` | `raw_email` |
| `person.phone`       | `dataPhone` | `raw_phone` |
| `person.fax`         | `dataFax` | `raw_fax` |
| `person.title`       | `dataTitle` | `raw_title` |
| `job.job_title`      | `dataJobTitle` | `raw_job_title` |
| `job.job_type`       | `dataPositionType` | `raw_position_type` |
| `job.start_date`     | `dataJobStartDate` | `raw_date` |
| `organization.org_name`   | `dataOrganization` | `raw_org_name` |
| `organization.org_vivo_uri` | `dataURI` | `raw_uri` |

**Key `data_1.csv` quirks** (confirmed by inspecting the file):
- Delimiter is `;` (not `,`) → read with `pd.read_csv(..., sep=";")`.
- File is `UTF-8 with BOM` and `CRLF` line endings → read with `encoding="utf-8-sig"`.
- Values are read as strings with `dtype=str` (and `keep_default_na=False` where relevant) so
  pandas does not silently coerce identifiers.
- `dataFirstNames` is `"first, middle"` in some rows (`"Edgar, Estes"`) and just `"first"` in
  others → split on the first `", "` occurrence, not on every comma.

---

## 5. Architecture (directory layout)

```
de-test/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app factory, router registration, lifespan (DB init)
│   ├── config.py               # pydantic-settings: DB_PATH, etc.
│   ├── db.py                   # DuckDB connection (per-request or shared), schema bootstrap
│   ├── models/
│   │   ├── __init__.py
│   │   ├── record.py           # IngestedRecord / Person / Organization / Job
│   │   └── responses.py        # UploadSummary response model
│   ├── schemas/
│   │   └── schema.sql          # DDL from §3
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py       # GET /health
│   │       └── upload.py       # POST /upload
│   ├── parsers/                # Strategy + Registry (the extensibility core)
│   │   ├── __init__.py         # builds & exports the default registry
│   │   ├── base.py             # FormatHandler ABC (probe + parse)
│   │   ├── registry.py         # FormatRegistry
│   │   └── formats/            # one module per concrete file format (the "strategies")
│   │       ├── __init__.py
│   │       ├── csv_format_1.py  # CSVFormatHandler  (data_1 style)
│   │       └── xlsx_format_1.py # XLSXFormatHandler (data_2/3/4 style)
│   └── services/
│       ├── __init__.py
│       ├── ingest.py           # orchestration: probe → parse → upsert → summary
│       ├── repository.py       # all DuckDB SQL (upsert/dedup/update/history)
│       └── history.py          # diff computation + history writes
├── tests/
│   ├── conftest.py             # in-memory DuckDB + TestClient fixtures
│   ├── fixtures/               # small hand-crafted .csv / .xlsx samples
│   ├── test_models.py
│   ├── test_formats.py         # registry probing + both parsers
│   ├── test_repository.py      # dedup, upsert, update, history (in-memory DB)
│   └── test_api_upload.py      # endpoint + HTTP error codes
├── data/                       # provided input files (untouched)
├── data_db/                    # host bind-mounted DuckDB dir (runtime, gitignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── IMPLEMENTATION_PLAN.md      # this file
```

---

## 6. Core pattern — Strategy + Registry

The test explicitly wants **file-type probing separated from format handling**, so a new format
can be added with a new parser without touching the API or the DB.

### 6.1 The strategy interface

```python
# app/parsers/base.py
from abc import ABC, abstractmethod
from app.models.record import IngestedRecord

class FormatHandler(ABC):
    """Strategy interface. One concrete class per file format."""
    format_id: str                     # e.g. "csv_format_1", "xlsx_format_1"

    @abstractmethod
    def probe(self, filename: str, content: bytes) -> bool:
        """Return True if this handler recognizes the file (content + extension)."""

    @abstractmethod
    def parse(self, content: bytes) -> list[IngestedRecord]:
        """Parse raw bytes into canonical records. Raise InvalidFormatError on failure."""
```

`probe` answers *"is this format something I know how to handle?"*, `parse` answers
*"transform it into canonical records"*. They are invoked at two distinct stages of the pipeline.

### 6.2 The registry

```python
# app/parsers/registry.py
from app.parsers.base import FormatHandler

class FormatRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, FormatHandler] = {}

    def register(self, handler: FormatHandler) -> None:
        self._handlers[handler.format_id] = handler

    def probe(self, filename: str, content: bytes) -> FormatHandler | None:
        """Return the first handler whose probe() accepts the file, else None."""
        for h in self._handlers.values():
            if h.probe(filename, content):
                return h
        return None

    def supported_extensions(self) -> list[str]:
        ...
```

The registry is built once at startup (`app/parsers/__init__.py`) and attached to
`app.state.registry`. Probing is content-first with extension fallback. Each concrete handler
lives in its own module under `app/parsers/formats/`:

```python
# app/parsers/formats/csv_format_1.py
class CSVFormatHandler(FormatHandler):
    format_id = "csv_format_1"
    def probe(self, filename, content):
        return filename.lower().endswith(".csv") or self._looks_like_semicolon_csv(content)

# app/parsers/formats/xlsx_format_1.py
class XLSXFormatHandler(FormatHandler):
    format_id = "xlsx_format_1"
    def probe(self, filename, content):
        return filename.lower().endswith(".xlsx") or content[:4] == b"PK\x03\x04"
```

### 6.3 Adding a new format (the whole point)

1. Create `app/parsers/formats/<ext>_format_N.py` with a `FormatHandler` subclass.
   A new variant of an existing extension is a new file — e.g. `csv_format_2.py` for a second,
   differently-shaped CSV, `xlsx_format_2.py` for a differently-laid-out Excel sheet, and so on.
2. Register it in `app/parsers/__init__.py`.
3. Write a parser test in `tests/test_formats.py`.

No changes to `upload.py`, `repository.py`, the DB schema, or the Docker setup.

---

## 7. Historisation — mechanism & justification

**Decision (product choice): use an append-only audit table (`person_history`), written by the
application layer.**

```sql
person_history(history_id, person_id, field_name, old_value, new_value,
               version, source_file, changed_at)
```

When a person is updated, we compute a field-level diff (`email`, `phone`, `fax`, `title`) and
write **one row per changed field**, incrementing a `version` counter.

**Why this mechanism (comparison with the alternatives):**

| Mechanism | Verdict | Reason |
|---|---|---|
| **App-level audit table (chosen)** | ✅ | Simple, portable across DBs, exact field-level diff, no read-path impact, easy to unit-test, trivial to query "who/what/when". |
| SCD Type 2 (`valid_from/valid_to` + current flag on `person`) | ⚠️ | Great for point-in-time snapshots, but complicates the `job → person` FK and the dedup/upsert logic; heavier than needed here. |
| DB triggers | ⚠️ | Couples history to DuckDB-specific trigger syntax; harder to unit-test and less portable. |
| Full row snapshots (`person_versions` table) | ⚠️ | Simpler to implement than field diffs but more storage and less precise ("which field changed?" requires diffing snapshots). |

The field-level audit table is the chosen approach: it is explicit, testable, and answers both
"what changed" and "what was it before".

### 7.1 Field-value priority ("latest wins")

When the same person is re-uploaded, a field may carry a different value than the one already in
the canonical `person` table. The rule for deciding **which value ends up in the canonical table**
is: **keep the latest ingested value, whenever it differs from the previously stored value** —
i.e. the most recently *processed* row wins.

This is deliberately a *recency-of-ingestion* rule, not a *recency-of-data* rule. It makes the
pipeline idempotent and forgiving: if a file was ingested with an error (a wrong phone number,
for example), the operator can simply re-upload a corrected version of the file, and the corrected
value overwrites the previous one, regardless of the `start_date` / `raw_date` values present in
the files.

An alternative, equally valid approach would be to use a **business date column as the recency
priority** — e.g. keep the value from the row with the most recent `raw_date`. That approach is
better when a date column is a trustworthy source of truth about when each fact actually changed.
We reject it for the MVP because the only date available is a job `start_date`, which is a
property of the *job*, not of the *person's contact details*: using it to arbitrate person fields
would be semantically wrong (a person with an old job could still have the newest phone number).
If a genuine "last modified" timestamp ever appears in the source data, switching to the
date-based rule would be a localized change in `history.py` / `repository.py`.

---

## 8. Ingest pipeline (`app/services/ingest.py`)

```
POST /upload (multipart file)
        │
        ▼
 1. read file bytes  ───────────────────────────► empty → 400
        │
        ▼
 2. registry.probe(filename, content) ──────────► None → 415 Unsupported Media Type
        │
        ▼
 3. handler.parse(content) ─────────────────────► parse/validation error → 422
        │            (returns list[IngestedRecord])
        ▼
 4. repository.upsert(records, source_file)
        │   ┌─ for each record:
        │   │   a. upsert organization  (dedup on org_name+uri)
        │   │   b. upsert person        (dedup on first+middle+last)
        │   │        • new person      → INSERT
        │   │        • existing person → diff fields, UPDATE contact cols, write history
        │   │   c. upsert job           (dedup on person+org+title+type+date)
        │   └─ returns counters (persons_created, persons_updated,
        │                         jobs_created, orgs_created)
        ▼
 5. return UploadSummary (200)
```

### 8.1 Upsert / dedup semantics

- **Organization**: `INSERT OR IGNORE` on `(org_name, org_vivo_uri)` (sentinels applied), then
  select its `org_id`.
- **Person**: look up by `(first_name, middle_name, last_name)`.
  - Not found → `INSERT`, return new `person_id`, count as `created`.
  - Found → compare `email/phone/fax/title`; if any differ, `UPDATE` and write `person_history`
    rows; count as `updated`.
- **Job**: `INSERT OR IGNORE` on `(person_id, org_id, job_title, job_type, start_date)`
  (sentinels applied); count as `created` only when actually inserted.
  This is how "new jobs are inserted" for existing persons, while strictly-identical jobs are
  never duplicated.

Surrogate keys are generated with DuckDB sequences (`nextval('person_seq')` etc.). DuckDB supports
`INSERT … ON CONFLICT DO NOTHING` and `INSERT OR IGNORE`; we use `INSERT OR IGNORE`, which respects
the plain unique indexes once all dedup columns are non-`NULL` (see §3.3).

### 8.2 Update interpretation note

"Coordonnées" is interpreted as the person's contact/identity attributes `email`, `phone`, `fax`,
and `title` (the test states these are attributes of `person`). All four are updated on re-upload
of an existing person; `first/middle/last` are the immutable identity key and never change.

---

## 9. API contract

| Endpoint | Method | Input | Success | Errors |
|---|---|---|---|---|
| `/health` | GET | — | `200 {"status":"ok"}` | — |
| `/upload` | POST | multipart file field `file` | `200` + `UploadSummary` | `400`, `415`, `422`, `500` |

`UploadSummary` (Pydantic response model):

```python
class UploadSummary(BaseModel):
    format: str
    persons_created: int
    persons_updated: int
    jobs_created: int
    organizations_created: int
    history_rows_written: int
```

**Error semantics:**

| Code | Condition |
|---|---|
| `400 Bad Request` | Missing `file` part, or empty (zero-byte) file. |
| `415 Unsupported Media Type` | `registry.probe()` returns `None` (unknown/unsupported format). |
| `422 Unprocessable Entity` | Pydantic `ValidationError` or `InvalidFormatError` (e.g. missing required column, malformed row, bad type). |
| `500 Internal Server Error` | Unexpected exception (caught by a global handler). |

---

## 10. Docker

### 10.1 `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# pandas/numpy ship manylinux wheels for python:3.12-slim, so usually no system deps are needed
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ ./app/

# Data files (input examples)
COPY data/ ./data/

# The DB lives on the host (bind-mounted at runtime, see docker-compose.yml);
# create its mount dir so a standalone `docker run` also works.
RUN mkdir -p /app/db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The DB path is configurable via env var (`DUCKDB_PATH`), defaulting to a file bind-mounted from
the host so it survives container restarts and is directly inspectable on the host.

### 10.2 `docker-compose.yml`

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      DUCKDB_PATH: /app/db/app.duckdb     # in-container path (parameterized)
    volumes:
      - ./data_db:/app/db                 # bind mount: DB lives on the host
```

The database file is **externalized**: it lives in the host folder `./data_db` (create it with
`mkdir -p data_db`; it is gitignored). You can point any DuckDB client at `./data_db/app.duckdb`
when the API is stopped, or relocate it by overriding `DUCKDB_PATH` / the bind source.

### 10.3 Startup bootstrap

On startup (`lifespan`), the app:
1. Opens the DuckDB connection at `DUCKDB_PATH`.
2. Applies `app/schemas/schema.sql` idempotently (`CREATE TABLE IF NOT EXISTS`, unique indexes).
3. Builds and stores the `FormatRegistry` on `app.state`.

This way the image can start from either a copied pre-built DB or a fresh empty one.

### 10.4 `requirements.txt` (pin versions)

```
fastapi
uvicorn[standard]
pydantic>=2
pydantic-settings
duckdb
pandas
openpyxl         # engine used by pandas.read_excel for .xlsx
python-multipart
# dev
pytest
httpx            # for TestClient
pytest-cov
```

### 10.5 Database persistence & inspection

The DB is a single file on the host (`./data_db/app.duckdb`). To inspect it with arbitrary SQL,
stop the API (releasing the single-writer lock), query the file with any DuckDB client (DuckDB
CLI, the project venv, DBeaver, …), then start it again:

```bash
docker compose stop api
duckdb data_db/app.duckdb   # or any DuckDB client
docker compose start api
```

---

## 11. Testing strategy (pytest)

Use an **in-memory DuckDB** (`:memory:`) per test so tests are fast and isolated. `conftest.py`
provides fixtures: a fresh DB + schema, a repository instance, and a FastAPI `TestClient`.

### 11.1 `tests/test_models.py` — Pydantic validation

- Canonical record builds correctly; optional fields default (`middle_name=""`, nullable contacts).
- Required field missing → `ValidationError`.
- `start_date`/type coercion from string year → int (or explicit error if non-numeric).

### 11.2 `tests/test_formats.py` — probing & parsing (the extensibility core)

- `CSVFormatHandler.probe` accepts `.csv` bytes; `XLSXFormatHandler.probe` accepts `.xlsx` bytes.
- `registry.probe("foo.csv", …)` returns CSV handler; `("foo.xlsx", …)` returns XLSX handler.
- `registry.probe("foo.json", …)` / `.txt` / unknown → `None`.
- CSV parser:
  - reads `;` delimiter + `utf-8-sig` BOM + CRLF correctly.
  - splits `"Edgar, Estes"` → `first="Edgar"`, `middle="Estes"`.
  - `"Rosella"` → `first="Rosella"`, `middle=""`.
  - trims `"Professor "` → `"Professor"`.
  - maps `dataPositionType → job_type`, `dataJobTitle → job_title`,
    `dataOrganization → org_name`, `dataURI → org_vivo_uri`, `dataJobStartDate → start_date`.
  - returns `list[IngestedRecord]` that passes Pydantic validation.
- XLSX parser:
  - maps `raw_first/raw_last/raw_middle/…/raw_date/raw_uri`.
  - `raw_middle = NaN` → `""`.
  - `raw_date` int → int `start_date`.
  - missing/unknown column → raises `InvalidFormatError`.

Fixtures are **small hand-crafted files** in `tests/fixtures/` (a 3-row CSV, a 3-row XLSX) so
tests don't depend on the real `data/` files. Optionally, one integration test uses the real
`data_*.xlsx`/`data_1.csv` to assert end-to-end counts.

### 11.3 `tests/test_repository.py` — dedup, upsert, update, history (in-memory DB)

- Insert same person twice (same first/middle/last) → 1 row, second is a no-op.
- Insert same organization twice → 1 row.
- Insert strictly-identical job twice → 1 row (job dedup).
- Re-upload same person with changed `email/phone/fax/title` → `person` updated; 4 `person_history`
  rows; unchanged fields produce **no** history row.
- Existing person + new job (new `job_title`/`start_date`) → new `job` row inserted.
- New person (e.g. from `data_3`) → person + job inserted.
- `version` increments across consecutive updates.
- History rows record correct `old_value` / `new_value` and `source_file`.

### 11.4 `tests/test_api_upload.py` — endpoint + HTTP error codes

- `POST /upload` with a valid CSV fixture → `200`, summary counts correct.
- `POST /upload` with a valid XLSX fixture → `200`.
- `POST /upload` with `.txt`/`.json` (or no extension + unrecognized content) → **`415`**.
- `POST /upload` with empty file → **`400`**.
- `POST /upload` missing the `file` part → **`422`** (FastAPI default) or `400` (we choose one and test it).
- `POST /upload` with a valid-extension but malformed content (missing required column) → **`422`**.
- Full subsidiaire scenario: upload `data_1.csv` + `data_2.xlsx`, then `data_3.xlsx` + `data_4.xlsx`
  → assert persons updated (e.g. `Kimberly Mullins`, `Andrea Pate`, `Angelina Sims`), new persons
  created, new jobs inserted, no duplicate persons, and history rows written.
- `GET /health` → `200`.

---

## 12. Step-by-step implementation sequence

Each step lists the deliverable and the tests that must pass before moving on.

| # | Step | Files | Acceptance tests |
|---|---|---|---|
| 1 | Scaffold project: `requirements.txt`, package skeleton, `config.py`, empty `main.py` | `app/__init__.py`, `app/config.py`, `requirements.txt` | app imports cleanly |
| 2 | Canonical Pydantic models | `app/models/record.py` | `test_models.py` |
| 3 | SQL schema | `app/schemas/schema.sql` | schema applies to `:memory:` without error |
| 4 | DB layer + schema bootstrap | `app/db.py` | connection opens, schema applied idempotently |
| 5 | Format layer: `base.py`, `registry.py` | `app/parsers/base.py`, `app/parsers/registry.py` | registry registers/probes handlers (stub) |
| 6 | CSV parser (data_1 style) | `app/parsers/formats/csv_format_1.py` | `test_formats.py` CSV cases |
| 7 | XLSX parser (data_2/3/4 style) | `app/parsers/formats/xlsx_format_1.py` | `test_formats.py` XLSX cases |
| 8 | Register default handlers | `app/parsers/__init__.py`, `app/parsers/formats/__init__.py` | registry probe returns correct handler per file |
| 9 | Repository (upsert/dedup/update/history) | `app/services/repository.py`, `app/services/history.py` | `test_repository.py` |
| 10 | Ingest orchestration | `app/services/ingest.py` | unit test of the pipeline with stubs |
| 11 | API routes (`/upload`, `/health`) + error handling | `app/api/routes/*.py`, `app/main.py` | `test_api_upload.py` |
| 12 | End-to-end with real `data/` files | (integration test) | subsidiaire scenario in `test_api_upload.py` |
| 13 | Docker (bind-mounted externalized DB) | `Dockerfile`, `docker-compose.yml` | `docker compose up` → `GET /health` 200; upload works; DB visible in `./data_db` |
| 14 | README | `README.md` | run instructions reproduce full use-case |

---

## 13. `README.md` outline (deliverable requirement)

1. Overview + architecture diagram (short).
2. Prerequisites (Docker, docker-compose).
3. Build & run: `docker compose up --build`; API at `http://localhost:8000`.
4. Endpoints (`/health`, `/upload`) with a `curl` example for each.
5. Step-by-step reproduction of the use-case:
   - `curl -F "file=@data/data_1.csv" http://localhost:8000/upload`
   - `curl -F "file=@data/data_2.xlsx" ...`
   - `curl -F "file=@data/data_3.xlsx" ...`
   - `curl -F "file=@data/data_4.xlsx" ...`
   - expected outcomes at each step (counts, updates).
6. How to run tests: `docker compose run --rm api pytest` (or locally `pytest`).
7. How to inspect the DB offline: `./data_db/app.duckdb` (§10.5).
8. How to add a new format (3-step recipe, §6.3).
9. Historisation rationale (link to §7).

---

## 14. Edge cases & risks to handle

- **`data_1.csv` delimiter is `;`** — a naive `pd.read_csv` with the default `sep=","` would
  break. Pass `sep=";"` explicitly.
- **UTF-8 BOM + CRLF** in `data_1.csv` — read with `encoding="utf-8-sig"`.
- **pandas type coercion** — read every column as `dtype=str` and use `keep_default_na=False` /
  explicit NaN handling so identifiers and phone numbers aren't mangled.
- **Trailing spaces** in `data_1.csv` (`"Professor "`, `"Associate Curator "`) — strip all strings.
- **`NaN`/empty middle names in XLSX** — normalize to `""`.
- **NULL in unique indexes** — solved via `''`/`-1` sentinels (see §3.3); test explicitly.
- **`raw_date` dtype** is `int64` in the XLSX files but string in CSV — normalize to `INTEGER`.
- **Version pinning** — pin `duckdb` (and all deps) to avoid `ON CONFLICT` syntax drift.
- **Large files** — MVP reads file into memory; acceptable for the test, note streaming as a
  future improvement.
- **Concurrent uploads / external queries** — DuckDB native format is single-writer: while the API
  holds the file open, no other process can open it (even read-only). Arbitrary external SQL
  therefore requires stopping the API first (or adopting DuckDB's Quack server mode). Documented
  limitation by design.

---

## 15. Out of scope (explicitly deferred)

- Authentication / authorization.
- Streaming ingestion of very large files.
- Full SCD Type 2 history (chose field-level audit instead — justified in §7).
- Additional normalization (e.g. a `department` table) — allowed but not required; kept to the
  3 required tables to stay within the half-day budget.
