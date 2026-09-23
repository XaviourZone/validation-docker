# PostgreSQL local setup

Required:
- database: validation
- user: validation
- host: 127.0.0.1
- port: 5432

Password is read from VALIDATION_PG_PASSWORD.

## Ubuntu

    sudo -u postgres psql

    CREATE USER validation WITH PASSWORD '<SET_LOCAL_PASSWORD>';
    ALTER USER validation CREATEDB;
    CREATE DATABASE validation OWNER validation;

## Windows

Use psql.exe from the PostgreSQL installation:

    psql -U postgres

    CREATE USER validation WITH PASSWORD '<SET_LOCAL_PASSWORD>';
    ALTER USER validation CREATEDB;
    CREATE DATABASE validation OWNER validation;

db_manager.py creates the schema automatically.

## Tables

Current reference:
- reference_wrs_current
- reference_pans_current
- reference_nsc_current

History:
- reference_wrs_history
- reference_pans_history
- reference_nsc_history

Configuration:
- source
- field_mapping
- parser_mapping
- unlocode
- destination_mapping
- system_config

Operational:
- import_batch
- import_file
- pans_pending
- mmsi_history

Reference importers never physically delete WRS, NSC or PANS rows.
