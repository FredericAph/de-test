-- sequences for surrogate keys (DuckDB INTEGER PRIMARY KEY is not auto-incrementing)
CREATE SEQUENCE IF NOT EXISTS person_seq;
CREATE SEQUENCE IF NOT EXISTS organization_seq;
CREATE SEQUENCE IF NOT EXISTS job_seq;
CREATE SEQUENCE IF NOT EXISTS person_history_seq;

-- organization (dimension, referenced by job)
CREATE TABLE IF NOT EXISTS organization (
    org_id        INTEGER PRIMARY KEY,
    org_name      TEXT    NOT NULL,
    org_vivo_uri  TEXT    NOT NULL DEFAULT ''
);

-- person (dedup key = first_name + middle_name + last_name)
CREATE TABLE IF NOT EXISTS person (
    person_id    INTEGER PRIMARY KEY,
    first_name   TEXT    NOT NULL,
    middle_name  TEXT    NOT NULL DEFAULT '',
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
    job_type    TEXT    NOT NULL DEFAULT '',
    start_date  INTEGER NOT NULL DEFAULT -1
);

-- history / audit log
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

-- unique indexes enforcing dedup (plain indexes, no NULLs thanks to sentinels)
CREATE UNIQUE INDEX IF NOT EXISTS uq_person_identity
    ON person (first_name, middle_name, last_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization
    ON organization (org_name, org_vivo_uri);

CREATE UNIQUE INDEX IF NOT EXISTS uq_job
    ON job (person_id, org_id, job_title, job_type, start_date);
