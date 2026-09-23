# Ubuntu offline deployment

## PostgreSQL
PostgreSQL is an OS package/service, not a pip dependency.

On an internet-connected Ubuntu machine matching the offline host's Ubuntu release and CPU architecture, download PostgreSQL packages and all dependencies into a local package directory. Transfer the complete package set to the offline host and install it locally with apt/dpkg.

Create the local database user and database:

    sudo -u postgres psql

    CREATE USER validation WITH PASSWORD '<SET_LOCAL_PASSWORD>';
    ALTER USER validation CREATEDB;
    CREATE DATABASE validation OWNER validation;

Do not commit the password to Git. Set VALIDATION_PG_PASSWORD only on the deployment machine.

## Python wheels
On an internet-connected machine matching the target Python version and Ubuntu architecture:

    python3 -m pip download --only-binary=:all: -d offline_packages -r Validation/requirements-offline.txt

Transfer offline_packages to Ubuntu.

Install without Internet:

    python3 -m pip install --no-index --find-links=/path/to/offline_packages -r Validation/requirements-offline.txt

For Python 3.13 the wheel set must contain CPython 3.13 compatible wheels. Never copy Windows wheels to Ubuntu.

## Start DB manager

    bash Validation/DB_Manager/start_db.sh

Default web console:

    http://127.0.0.1:5050

## Map reference folders

Use Browse in the DB console.

WRS root must contain:
- Datasets/
- Decode files/ or Decode/

NSC root must contain both EAST and WEST sources.

PANS root is the folder containing incoming XML.

The Browse action uses the native folder chooser on the machine running db_manager.py.

## Individual feed test

Edit the top of a feed script:

    INPUT_TYPE="FOLDER"
    INPUT_FOLDER=r"/absolute/path/to/input"
    OUTPUT_FOLDER=r"/absolute/path/to/xml-output"
    RUN_ONCE=True

Then:

    python3 Validation/Feeds/SAIS_IOR.py

RUN_ONCE=True processes the current folder once and exits. Set RUN_ONCE=False for continuous operation.

The same method applies to SAIS_GLOBAL.py, MSIS.py, LRIT.py, VATMS_EAST.py, VATMS_WEST.py and NAIS.py.
