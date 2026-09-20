"""
WRS Importer - Dynamically loads WRS Datasets and Decode CSVs into SQLite.
"""

import argparse
import csv
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path for imports if run directly
import sys
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from Validation.Database.common.database_utils import (
    open_database,
    create_import_tracking_tables,
    integrity_check,
    get_table_row_counts
)
from Validation.Database.common.file_utils import discover_files, sha256_file
from Validation.Database.common.logging_utils import setup_logger

import yaml

def load_config(config_path):
    if not config_path:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "database.yaml"
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def clean_column_name(col):
    """Clean CSV header column to be a valid SQLite column name."""
    c = str(col).strip()
    if not c:
        return "UNKNOWN_COLUMN"
    # Replace spaces and special chars with underscores
    chars_to_replace = [" ", "-", ".", "/", "\\", "(", ")", "[", "]"]
    for char in chars_to_replace:
        c = c.replace(char, "_")
    return c.upper()

def infer_table_name(filename, is_decode=False):
    """
    Infer SQLite table name from filename.
    Examples:
      VESSELS.csv -> wrs_datasets_vessels
      wrs.datasets.VESSELS.csv -> wrs_datasets_vessels
      DECODE_AREA.csv -> wrs_decode_area
      wrs.decode.AREA.csv -> wrs_decode_area
    """
    base = Path(filename).stem.lower()
    
    if is_decode:
        if base.startswith("wrs.decode."):
            name = base[len("wrs.decode."):]
        elif base.startswith("decode_"):
            name = base[len("decode_"):]
        else:
            name = base
        return f"wrs_decode_{name.replace('.', '_')}"
    else:
        if base.startswith("wrs.datasets."):
            name = base[len("wrs.datasets."):]
        else:
            name = base
        return f"wrs_datasets_{name.replace('.', '_')}"

def create_table_from_headers(conn, table_name, headers):
    """Create SQLite table using TEXT for all columns."""
    if not headers:
        raise ValueError(f"No headers found for table {table_name}")
    
    cols = []
    for h in headers:
        cleaned = clean_column_name(h)
        # Avoid duplicate column names
        suffix = 1
        orig_cleaned = cleaned
        while cleaned in cols:
            cleaned = f"{orig_cleaned}_{suffix}"
            suffix += 1
        cols.append(cleaned)
        
    cols_def = ", ".join([f'"{c}" TEXT' for c in cols])
    
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({cols_def})')
    
    # Create index on VESSEL_ID if it exists
    if "VESSEL_ID" in cols:
        conn.execute(f'CREATE INDEX "idx_{table_name}_vessel_id" ON "{table_name}"("VESSEL_ID")')
    
    return cols

def process_csv_file(conn, file_path, batch_id, is_decode, batch_size=10000):
    """Process a single CSV file and load it into the database."""
    log = logging.getLogger("wrs_importer")
    start_time = time.monotonic()
    
    table_name = infer_table_name(file_path.name, is_decode)
    file_size = file_path.stat().st_size
    file_hash = sha256_file(file_path)
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO import_file 
        (batch_id, source_system, file_name, file_path, file_hash_sha256, file_size_bytes, target_table, discovered_at, status)
        VALUES (?, 'WRS', ?, ?, ?, ?, ?, datetime('now'), 'RUNNING')
    """, (batch_id, file_path.name, str(file_path), file_hash, file_size, table_name))
    file_id = cur.lastrowid
    conn.commit()

    rows_loaded = 0
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                raise ValueError("Empty CSV file")
            
            cols = create_table_from_headers(conn, table_name, headers)
            placeholders = ",".join(["?"] * len(cols))
            insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
            
            batch = []
            for row in reader:
                # Pad row if it has fewer columns than headers
                if len(row) < len(cols):
                    row.extend([""] * (len(cols) - len(row)))
                # Truncate if it has more
                elif len(row) > len(cols):
                    row = row[:len(cols)]
                    
                batch.append(row)
                
                if len(batch) >= batch_size:
                    conn.executemany(insert_sql, batch)
                    rows_loaded += len(batch)
                    batch = []
                    
            if batch:
                conn.executemany(insert_sql, batch)
                rows_loaded += len(batch)
                
        conn.commit()
        
        cur.execute("""
            UPDATE import_file 
            SET loaded_at = datetime('now'), status = 'COMPLETED', rows_loaded = ?
            WHERE file_id = ?
        """, (rows_loaded, file_id))
        conn.commit()
        
        log.info(f"Loaded {table_name}: {rows_loaded} rows in {time.monotonic() - start_time:.2f}s")
        return True, rows_loaded
        
    except Exception as e:
        conn.rollback()
        log.error(f"Failed to process {file_path.name}: {e}")
        cur.execute("""
            UPDATE import_file 
            SET loaded_at = datetime('now'), status = 'FAILED', error_message = ?
            WHERE file_id = ?
        """, (str(e), file_id))
        conn.commit()
        return False, 0

def run_import(config, dry_run=False):
    log = logging.getLogger("wrs_importer")
    
    db_config = config.get('database', {}).get('wrs', {})
    import_config = config.get('imports', {}).get('wrs', {})
    
    db_path = Path(project_root) / db_config.get('path', 'Validation/Database/WRS/wrs.db')
    staging_path = Path(project_root) / import_config.get('staging_db', 'Validation/Database/WRS/wrs_staging.db')
    input_dir = Path(project_root) / import_config.get('input_dir', 'Validation/Database/WRS/RAW_DATA')
    batch_size = import_config.get('batch_size', 10000)
    
    def find_dir(parent, names):
        wanted = {name.casefold() for name in names}
        if not parent.is_dir():
            return None
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() in wanted:
                return child
        return None

    datasets_dir = find_dir(input_dir, ("Datasets", "datasets"))
    decode_dir = find_dir(input_dir, ("Decode files", "decode", "Decode Files", "decode files"))

    # Fallback to older directory names if present
    sample_root = input_dir.parent.parent.parent.parent / "Sample data" / "WRS"
    if datasets_dir is None:
        datasets_dir = find_dir(sample_root, ("Datasets", "datasets"))
    if decode_dir is None:
        decode_dir = find_dir(sample_root, ("Decode Files", "Decode files", "decode", "decode files"))
    
    log.info(f"Starting WRS import. Datasets: {datasets_dir}, Decode: {decode_dir}")
    
    dataset_files = discover_files(datasets_dir, [".csv"])
    decode_files = discover_files(decode_dir, [".csv"])
    all_files = dataset_files + decode_files
    
    if not all_files:
        log.error("No WRS CSV files found.")
        return False
        
    if dry_run:
        log.info(f"DRY RUN: Discovered {len(dataset_files)} dataset files and {len(decode_files)} decode files.")
        for f in all_files:
            log.info(f"Would process: {f.name} -> {infer_table_name(f.name, f in decode_files)}")
        return True
        
    log.info(f"Discovered {len(dataset_files)} dataset files and {len(decode_files)} decode files.")
    
    # Remove old staging if exists
    if staging_path.exists():
        staging_path.unlink()
        
    conn = open_database(staging_path)
    create_import_tracking_tables(conn)
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO import_batch (source_system, started_at, status, files_discovered)
        VALUES ('WRS', datetime('now'), 'RUNNING', ?)
    """, (len(all_files),))
    batch_id = cur.lastrowid
    conn.commit()
    
    total_loaded = 0
    files_loaded = 0
    errors = 0
    
    for f in dataset_files:
        success, rows = process_csv_file(conn, f, batch_id, is_decode=False, batch_size=batch_size)
        if success:
            files_loaded += 1
            total_loaded += rows
        else:
            errors += 1
            
    for f in decode_files:
        success, rows = process_csv_file(conn, f, batch_id, is_decode=True, batch_size=batch_size)
        if success:
            files_loaded += 1
            total_loaded += rows
        else:
            errors += 1
            
    # Validate
    if errors > 0:
        log.error(f"Import failed with {errors} file errors. Staging database will NOT replace active.")
        status = 'FAILED'
        replace_db = False
    elif not integrity_check(conn):
        log.error("Staging database failed SQLite integrity check. Staging database will NOT replace active.")
        status = 'FAILED_INTEGRITY'
        replace_db = False
    else:
        status = 'COMPLETED'
        replace_db = True
        
    cur.execute("""
        UPDATE import_batch
        SET completed_at = datetime('now'), status = ?, files_loaded = ?, rows_loaded = ?, error_count = ?
        WHERE batch_id = ?
    """, (status, files_loaded, total_loaded, errors, batch_id))
    conn.commit()
    conn.close()
    
    if replace_db:
        # Atomic-ish replacement
        log.info("Import successful. Replacing active database...")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Backup existing just in case
        if db_path.exists():
            backup_dir = db_path.parent.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"wrs_pre_replace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(db_path, backup_path)
            log.info(f"Backed up active db to {backup_path.name}")
            
        shutil.move(staging_path, db_path)
        log.info(f"Active database updated. Loaded {files_loaded} files, {total_loaded} rows.")
        return True
    else:
        log.warning("WRS active database was not replaced due to errors.")
        return False

def main():
    parser = argparse.ArgumentParser(description="WRS Data Importer")
    parser.add_argument("--config", help="Path to database.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Discover files without importing")
    args = parser.parse_args()
    
    config = load_config(args.config)
    log_dir = Path(project_root) / config.get('logging', {}).get('log_dir', 'Validation/Database/logs')
    log_level = getattr(logging, config.get('logging', {}).get('level', 'INFO').upper(), logging.INFO)
    
    setup_logger("wrs_importer", log_dir=log_dir, level=log_level)
    
    try:
        run_import(config, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logging.getLogger("wrs_importer").info("Import cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logging.getLogger("wrs_importer").exception("Fatal error during import.")
        sys.exit(1)

if __name__ == "__main__":
    main()
