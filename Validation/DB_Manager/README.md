# Validation PostgreSQL DB Manager

This is the **single shared database controller** for the independent feed scripts.

## Responsibilities

- PostgreSQL database: `validation`
- PANS live XML monitoring
- WRS manual update
- NSC manual update
- current + history retention
- source IDs
- field mappings
- UN/LOCODE and destination mappings
- vessel/reference search
- local web console

The DB manager does **not** parse SAIS/MSIS/LRIT/VATMS/NAIS feed data and does not provide a common feed-processing pipeline.

## Default folders

```
Validation/
  DB_Data/
    PANS/
    WRS/
    NSC/
```

You can override them with environment variables:

- `VALIDATION_PANS_INPUT_DIR`
- `VALIDATION_WRS_INPUT_DIR`
- `VALIDATION_NSC_INPUT_DIR`

## PostgreSQL

Default connection:

- host: `127.0.0.1`
- port: `5432`
- database: `validation`
- user: `validation`

The DB manager creates the database if PostgreSQL is already running and the configured PostgreSQL account has permission.

If you use a local PostgreSQL ZIP installation, set:

```
VALIDATION_PG_CTL=C:\path\to\pg_ctl.exe
VALIDATION_PG_DATA=C:\path\to\data
```

For Ubuntu/system PostgreSQL, install PostgreSQL normally and start its service before running the manager, or use `start_db.sh`.

## Web console

Default: `http://127.0.0.1:5050`

The console shows reference counts and allows:

- WRS update
- NSC update
- immediate PANS processing
- vessel search
- mapping editing
- source editing through API
- UN/LOCODE editing
- destination editing

## Reference update semantics

No reference rows are physically deleted by WRS, NSC or PANS imports.

When a current row changes:

1. old current JSON is copied to the matching history table;
2. current row is updated;
3. new data becomes current.

If a monthly WRS/NSC file no longer contains a previous row, the previous row remains. This follows the project requirement that updates must not delete historical information.

## PANS outage behavior

PANS files remain in the input directory until they are successfully processed. If PostgreSQL is temporarily unavailable, the monitor logs the failure and retries later. A failed/invalid file is never silently deleted.

## Offline packages

On an internet-connected machine:

```
python -m pip download --only-binary=:all: -d offline_packages -r Validation/DB_Manager/requirements.txt
```

Move the complete `offline_packages` directory to Ubuntu and install:

```
python3 -m pip install --no-index --find-links=/opt/validation/offline_packages -r Validation/DB_Manager/requirements.txt
```

For Python 3.13, use wheels matching the target architecture. Do not copy a Windows wheel to Ubuntu.

## PostgreSQL offline installation

PostgreSQL itself is an OS package/service and is separate from the Python wheels. On an internet-connected Ubuntu machine of the same release/architecture, download the required PostgreSQL `.deb` packages and dependencies, transfer them to the offline host, and install them with `dpkg`/the local apt cache. Then create the local PostgreSQL role/database as required.

The Validation repository deliberately does not bundle PostgreSQL binaries.
