"""
PANS Importer - Live continuous XML importer for PANS (VESPRO, CALINF, CALINV, BERMAN).
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import threading

import sys
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from Validation.Database.common.database_utils import (
    open_database,
    create_import_tracking_tables,
)
from Validation.Database.common.file_utils import is_file_stable, sha256_file
from Validation.Database.common.logging_utils import setup_logger

import yaml

# PANS XML Root to Table mapping
PANS_TABLES = {
    "VesselProfile": "pans_vespro",
    "VoyageRegistration": "pans_calinf",
    "VesselCallNumber": "pans_calinv",
    "BerthManagement": "pans_berman"
}

def load_config(config_path):
    if not config_path:
        config_path = Path(project_root) / "Validation" / "Database" / "config" / "database.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def flatten_xml(element, prefix="", result=None):
    """
    Recursively flatten XML into a dictionary.
    Keys are tag names. If there are multiple identical tags, 
    they will be joined by semicolons.
    """
    if result is None:
        result = {}
        
    tag = element.tag.split('}')[-1]  # Remove namespace if any
    
    # Process text content. XML source files can contain tags that differ
    # only by case (for example PortCode and Portcode). SQLite column names
    # are case-insensitive, so preserve the first spelling and merge values
    # under that canonical key instead of creating a duplicate column.
    if element.text and element.text.strip():
        val = element.text.strip()
        existing_key = next((k for k in result if k.lower() == tag.lower()), None)
        if existing_key is not None:
            result[existing_key] = f"{result[existing_key]}; {val}"
        else:
            result[tag] = val
            
    # Process children
    for child in element:
        flatten_xml(child, "", result)
        
    return result

def ensure_table_and_columns(conn, table_name, record_dict):
    """
    Ensure the table exists, and dynamically add any missing columns 
    based on the keys in record_dict.
    """
    cur = conn.cursor()
    
    # Check if table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cur.fetchone():
        # Create table with a primary key
        cur.execute(f"CREATE TABLE {table_name} (_id INTEGER PRIMARY KEY AUTOINCREMENT)")
        
    # Get existing columns
    cur.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row['name'] for row in cur.fetchall()}
    
    # Add missing columns
    for key in record_dict.keys():
        safe_key = str(key).replace("-", "_").replace(" ", "_")
        if safe_key not in existing_columns and safe_key != "_id":
            # Use TEXT for everything per requirement
            try:
                cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {safe_key} TEXT")
                existing_columns.add(safe_key)
            except sqlite3.OperationalError as e:
                # Handle edge cases where column might have been added concurrently
                pass
                
    return existing_columns

def _record_value(record, *names):
    """Return the first non-empty value matching any field name case-insensitively."""
    by_lower = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        value = by_lower.get(str(name).lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _upsert_pans_record(conn, table_name, record):
    """
    Upsert one PANS vessel record.

    Identity priority:
      1. IMONumber
      2. MMSINumber
      3. CallSign

    New XML for the same vessel updates the existing row instead of creating
    another duplicate row. Fields not present in the new XML are preserved.
    """
    cur = conn.cursor()

    identity_fields = (
        ("IMONumber", _record_value(record, "IMONumber")),
        ("MMSINumber", _record_value(record, "MMSINumber")),
        ("CallSign", _record_value(record, "CallSign")),
    )

    existing_row = None
    matched_field = None
    matched_value = None

    for field, value in identity_fields:
        if not value:
            continue
        safe_field = str(field).replace("-", "_").replace(" ", "_")
        cur.execute(
            f'SELECT _id FROM "{table_name}" '
            f'WHERE "{safe_field}" = ? ORDER BY _id DESC LIMIT 1',
            (value,),
        )
        row = cur.fetchone()
        if row:
            existing_row = row
            matched_field = field
            matched_value = value
            break

    if existing_row:
        # Update only fields supplied by this XML. This prevents a partial
        # PANS message from erasing already-known vessel attributes.
        assignments = []
        values = []
        for column, value in record.items():
            safe_column = str(column).replace("-", "_").replace(" ", "_")
            if safe_column == "_id":
                continue
            if value is None or not str(value).strip():
                continue
            assignments.append(f'"{safe_column}" = ?')
            values.append(str(value))

        if assignments:
            values.append(existing_row[0])
            cur.execute(
                f'UPDATE "{table_name}" SET {", ".join(assignments)} WHERE _id = ?',
                values,
            )

        log = logging.getLogger("pans_importer")
        log.info(
            f"Updated {table_name} for {matched_field}={matched_value} "
            f"(row_id={existing_row[0]})"
        )
        return "updated"

    cols = list(record.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_names = ",".join(f'"{str(col).replace("-", "_").replace(" ", "_")}"' for col in cols)
    values = [str(record[col]) for col in cols]
    cur.execute(
        f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
        values,
    )
    log = logging.getLogger("pans_importer")
    log.info(f"Inserted new {table_name} record")
    return "inserted"


def process_xml_file(conn, file_path, batch_id):
    """Parse XML and insert/update the appropriate PANS table."""
    log = logging.getLogger("pans_importer")
    
    file_hash = sha256_file(file_path)
    file_size = file_path.stat().st_size
    
    cur = conn.cursor()
    
    # Check duplicate
    cur.execute("SELECT file_id FROM import_file WHERE file_hash_sha256 = ? AND status = 'COMPLETED'", (file_hash,))
    if cur.fetchone():
        log.info(f"Skipping {file_path.name}: already processed.")
        return True # already done
        
    # Register file
    cur.execute("""
        INSERT INTO import_file 
        (batch_id, source_system, file_name, file_path, file_hash_sha256, file_size_bytes, discovered_at, status)
        VALUES (?, 'PANS', ?, ?, ?, ?, datetime('now'), 'RUNNING')
    """, (batch_id, file_path.name, str(file_path), file_hash, file_size))
    file_id = cur.lastrowid
    conn.commit()
    
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        root_tag = root.tag.split('}')[-1]
        
        if root_tag not in PANS_TABLES:
            raise ValueError(f"Unknown PANS XML root: {root_tag}")
            
        table_name = PANS_TABLES[root_tag]
        
        # Update target table
        cur.execute("UPDATE import_file SET target_table = ? WHERE file_id = ?", (table_name, file_id))
        
        # Flatten
        record = flatten_xml(root)
        
        # Keep keys safe for sqlite
        safe_record = {str(k).replace("-", "_").replace(" ", "_"): str(v) for k, v in record.items()}
        
        # Ensure schema
        ensure_table_and_columns(conn, table_name, safe_record)
        
        # Insert or update the vessel record. PANS is a live reference feed:
        # repeated XML for the same vessel must refresh the existing record.
        action = _upsert_pans_record(conn, table_name, safe_record)

        cur.execute("""
            UPDATE import_file
            SET loaded_at = datetime('now'), status = 'COMPLETED', rows_loaded = 1
            WHERE file_id = ?
        """, (file_id,))
        conn.commit()
        
        log.info(f"Loaded {file_path.name} -> {table_name}")
        return True
        
    except Exception as e:
        conn.rollback()
        log.error(f"Failed to process {file_path.name}: {e}")
        cur.execute("""
            UPDATE import_file 
            SET loaded_at = datetime('now'), status = 'FAILED', error_message = ?
            WHERE file_id = ?
        """, (str(e), file_id))
        conn.commit()
        return False

class PansLiveImporter:
    def __init__(self, config, config_path=None):
        self.config = config
        self.config_path = Path(config_path).resolve() if config_path else None
        self.config_mtime_ns = self.config_path.stat().st_mtime_ns if self.config_path and self.config_path.exists() else None
        self.log = logging.getLogger("pans_importer")
        self.running = False
        self.db_path = Path(project_root) / config.get('database', {}).get('pans', {}).get('path', 'Validation/Database/PANS/pans.db')
        import_cfg = config.get('imports', {}).get('pans', {})
        self.input_dir = Path(project_root) / import_cfg.get('input_dir', 'Validation/Database/PANS/RAW_DATA')
        self.poll_interval = float(import_cfg.get('poll_interval_seconds', 2.0))
        self.stability_seconds = float(import_cfg.get('stability_seconds', 1.0))
        self._apply_fallback_input_dir()
        self.conn = None
        self.batch_id = None

    def _apply_fallback_input_dir(self):
        if not self.input_dir.exists():
            fallback = self.input_dir.parent.parent.parent.parent / "Sample data" / "PANS"
            if fallback.exists():
                self.input_dir = fallback

    def _reload_config_if_changed(self):
        if not self.config_path or not self.config_path.exists():
            return
        try:
            mtime = self.config_path.stat().st_mtime_ns
            if self.config_mtime_ns == mtime:
                return
            new_config = load_config(self.config_path)
            import_cfg = new_config.get('imports', {}).get('pans', {})
            self.input_dir = Path(project_root) / import_cfg.get('input_dir', 'Validation/Database/PANS/RAW_DATA')
            self.poll_interval = float(import_cfg.get('poll_interval_seconds', self.poll_interval))
            self.stability_seconds = float(import_cfg.get('stability_seconds', self.stability_seconds))
            self.config = new_config
            self.config_mtime_ns = mtime
            self._apply_fallback_input_dir()
            self.log.info(f"Configuration reloaded. Monitoring: {self.input_dir}")
        except Exception as exc:
            self.log.error(f"Failed to reload database configuration: {exc}")
        
    def start(self, once=False):
        self.log.info(f"Starting PANS importer. Monitoring: {self.input_dir}")
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.running = True
        
        self.conn = open_database(self.db_path)
        create_import_tracking_tables(self.conn)
        
        # Start a batch for this run
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO import_batch (source_system, started_at, status)
            VALUES ('PANS', datetime('now'), 'RUNNING')
        """)
        self.batch_id = cur.lastrowid
        self.conn.commit()
        
        try:
            self._loop(once)
        except KeyboardInterrupt:
            self.log.info("Interrupted by user.")
        except Exception as e:
            self.log.exception("Fatal error in monitor loop.")
        finally:
            self.stop()
            
    def _loop(self, once):
        while self.running:
            files = [p for p in sorted(self.input_dir.iterdir()) if p.is_file() and p.suffix.lower() == '.xml']
            
            for f in files:
                if not self.running:
                    break

                if is_file_stable(f, self.stability_seconds):
                    process_xml_file(self.conn, f, self.batch_id)

            self._reload_config_if_changed()

            if once:
                break
                
            time.sleep(self.poll_interval)
            
    def stop(self):
        self.running = False
        if self.conn:
            try:
                cur = self.conn.cursor()
                cur.execute("UPDATE import_batch SET completed_at = datetime('now'), status = 'COMPLETED' WHERE batch_id = ?", (self.batch_id,))
                self.conn.commit()
                self.conn.close()
            except:
                pass
        self.log.info("PANS importer stopped.")

def main():
    parser = argparse.ArgumentParser(description="PANS Live Importer")
    parser.add_argument("--config", help="Path to database.yaml")
    parser.add_argument("--once", action="store_true", help="Process existing files and exit")
    args = parser.parse_args()
    
    config_path = Path(args.config).resolve() if args.config else None
    config = load_config(args.config)
    log_dir = Path(project_root) / config.get('logging', {}).get('log_dir', 'Validation/Database/logs')
    log_level = getattr(logging, config.get('logging', {}).get('level', 'INFO').upper(), logging.INFO)
    
    setup_logger("pans_importer", log_dir=log_dir, level=log_level)
    
    importer = PansLiveImporter(config, config_path=config_path)
    importer.start(once=args.once)

if __name__ == "__main__":
    main()
