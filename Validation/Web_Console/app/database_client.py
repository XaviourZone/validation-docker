"""Client for interacting with Validation Reference Databases and Importers."""

import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading

import yaml

class DatabaseClient:
    """Orchestrates database queries and importer process execution safely."""

    def __init__(self, workspace_root: Path, logger: logging.Logger, service_controller: Any, config_manager: Any = None):
        self.workspace_root = workspace_root
        self.logger = logger
        self.service_controller = service_controller
        self.config_manager = config_manager
        
        # Load config
        configured_db = os.environ.get("VALIDATION_DATABASE_CONFIG")
        self.db_config_path = Path(configured_db) if configured_db else self.workspace_root / "Validation" / "Database" / "config" / "database.yaml"
        self.config = self._load_config()
        
        self.wrs_path = self.workspace_root / self.config.get("database", {}).get("wrs", {}).get("path", "Validation/Database/WRS/wrs.db")
        self.pans_path = self.workspace_root / self.config.get("database", {}).get("pans", {}).get("path", "Validation/Database/PANS/pans.db")
        self.nsc_path = self.workspace_root / self.config.get("database", {}).get("nsc", {}).get("path", "Validation/Database/NSC/nsc.db")

        # Importer script paths
        self.wrs_importer_script = self.workspace_root / "Validation" / "Database" / "WRS" / "importer" / "wrs_importer.py"
        self.pans_importer_script = self.workspace_root / "Validation" / "Database" / "PANS" / "importer" / "pans_importer.py"
        self.nsc_importer_script = self.workspace_root / "Validation" / "Database" / "NSC" / "importer" / "nsc_importer.py"
        
        # Concurrency locks (in-memory)
        self.active_operations = {
            "wrs": False,
            "nsc": False,
            "pans_once": False
        }

    def _importer_command(self, script: Path, *args: str):
        command = [sys.executable, str(script)]
        configured = os.environ.get("VALIDATION_DATABASE_CONFIG")
        if configured:
            command.extend(["--config", configured])
        command.extend(args)
        return command

    def _load_config(self) -> dict:
        try:
            with open(self.db_config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.warning(f"Failed to load database config: {e}")
            return {}

    def _get_db_size(self, path: Path) -> float:
        if not path.exists():
            return 0.0
        return round(path.stat().st_size / (1024 * 1024), 2)  # MB

    def _get_last_import(self, conn: sqlite3.Connection) -> Tuple[str, str]:
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT completed_at, status FROM import_batch ORDER BY batch_id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return str(row["completed_at"]), str(row["status"])
        except sqlite3.OperationalError:
            pass
        return "Unknown", "UNKNOWN"

    def _get_table_counts(self, conn: sqlite3.Connection, prefix: str = "") -> Dict[str, int]:
        counts = {}
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('import_batch', 'import_file')")
            tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                if prefix and not table.startswith(prefix):
                    continue
                cur.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
        except sqlite3.OperationalError as e:
            self.logger.error(f"Error reading table counts: {e}")
        return counts

    def get_wrs_status(self) -> Dict[str, Any]:
        status = {
            "status": "MISSING",
            "database": self.wrs_path.name,
            "size_mb": 0.0,
            "table_count": 0,
            "row_count": 0,
            "last_import": "Unknown",
            "import_status": "UNKNOWN",
            "tables": {},
            "is_refreshing": self.active_operations["wrs"]
        }
        
        if self.wrs_path.exists():
            status["status"] = "READY"
            status["size_mb"] = self._get_db_size(self.wrs_path)
            try:
                conn = sqlite3.connect(f"file:{self.wrs_path}?mode=ro", uri=True)
                tables = self._get_table_counts(conn, "wrs_")
                status["tables"] = tables
                status["table_count"] = len(tables)
                status["row_count"] = sum(tables.values())
                last_ts, last_st = self._get_last_import(conn)
                status["last_import"] = last_ts
                status["import_status"] = last_st
                conn.close()
            except Exception as e:
                status["status"] = "ERROR"
                self.logger.error(f"Error checking WRS DB: {e}")
                
        if self.active_operations["wrs"]:
            status["status"] = "REFRESHING"
            
        return status

    def get_pans_status(self) -> Dict[str, Any]:
        status = {
            "status": "MISSING",
            "database": self.pans_path.name,
            "size_mb": 0.0,
            "table_count": 0,
            "row_count": 0,
            "last_update": "Unknown",
            "tables": {},
            "importer_status": "UNKNOWN",
            "files_processed": 0
        }

        # Check Importer Service Status
        svc_info = self.service_controller.get_service_status("validation-pans-importer.service")
        status["importer_status"] = svc_info.get("status", "UNKNOWN")

        if self.pans_path.exists():
            status["status"] = "LIVE"
            status["size_mb"] = self._get_db_size(self.pans_path)
            try:
                conn = sqlite3.connect(f"file:{self.pans_path}?mode=ro", uri=True)
                tables = self._get_table_counts(conn, "pans_")
                status["tables"] = tables
                status["table_count"] = len(tables)
                status["row_count"] = sum(tables.values())
                last_ts, _ = self._get_last_import(conn)
                status["last_update"] = last_ts
                
                # Files processed count
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM import_file WHERE status='PROCESSED'")
                status["files_processed"] = cur.fetchone()[0]
                
                conn.close()
            except Exception as e:
                status["status"] = "ERROR"
                self.logger.error(f"Error checking PANS DB: {e}")
                
        return status

    def get_nsc_status(self) -> Dict[str, Any]:
        status = {
            "status": "MISSING",
            "database": self.nsc_path.name,
            "size_mb": 0.0,
            "table_count": 0,
            "row_count": 0,
            "east_count": 0,
            "west_count": 0,
            "last_import": "Unknown",
            "import_status": "UNKNOWN",
            "tables": {},
            "is_refreshing": self.active_operations["nsc"]
        }
        
        if self.nsc_path.exists():
            status["status"] = "READY"
            status["size_mb"] = self._get_db_size(self.nsc_path)
            try:
                conn = sqlite3.connect(f"file:{self.nsc_path}?mode=ro", uri=True)
                tables = self._get_table_counts(conn, "nsc_")
                status["tables"] = tables
                status["table_count"] = len(tables)
                status["row_count"] = sum(tables.values())
                
                # Check regions if table exists
                if "nsc_vessels" in tables:
                    cur = conn.cursor()
                    cur.execute("SELECT SOURCE_REGION, count(*) FROM nsc_vessels GROUP BY SOURCE_REGION")
                    for row in cur.fetchall():
                        region = row[0]
                        count = row[1]
                        if region == "EAST":
                            status["east_count"] = count
                        elif region == "WEST":
                            status["west_count"] = count
                            
                last_ts, last_st = self._get_last_import(conn)
                status["last_import"] = last_ts
                status["import_status"] = last_st
                conn.close()
            except Exception as e:
                status["status"] = "ERROR"
                self.logger.error(f"Error checking NSC DB: {e}")
                
        if self.active_operations["nsc"]:
            status["status"] = "REFRESHING"
            
        return status

    def refresh_wrs(self) -> Dict[str, Any]:
        if self.active_operations["wrs"]:
            return {"success": False, "message": "WRS refresh is already running"}
            
        self.active_operations["wrs"] = True
        if self.config_manager:
            self.config_manager._log_audit_event("DB_WRS_REFRESH", "SYSTEM", {"message": "Started WRS full refresh"})
        try:
            cmd = self._importer_command(self.wrs_importer_script)
            self.logger.info("Executing WRS Importer...")
            def run_importer():
                try:
                    res = subprocess.run(cmd, cwd=str(self.workspace_root), capture_output=True, text=True)
                    if res.returncode == 0:
                        self.logger.info("WRS Import completed successfully.")
                    else:
                        self.logger.error(f"WRS Import failed: {res.stderr}")
                except Exception as e:
                    self.logger.error(f"WRS Import exception: {e}")
                finally:
                    self.active_operations["wrs"] = False
                    
            threading.Thread(target=run_importer, daemon=True).start()
            return {"success": True, "message": "WRS Refresh started"}
        except Exception as e:
            self.active_operations["wrs"] = False
            return {"success": False, "message": f"Failed to start WRS refresh: {e}"}

    def refresh_nsc(self) -> Dict[str, Any]:
        if self.active_operations["nsc"]:
            return {"success": False, "message": "NSC refresh is already running"}
            
        self.active_operations["nsc"] = True
        if self.config_manager:
            self.config_manager._log_audit_event("DB_NSC_REFRESH", "SYSTEM", {"message": "Started NSC full refresh"})
        try:
            cmd = self._importer_command(self.nsc_importer_script)
            self.logger.info("Executing NSC Importer...")
            def run_importer():
                try:
                    res = subprocess.run(cmd, cwd=str(self.workspace_root), capture_output=True, text=True)
                    if res.returncode == 0:
                        self.logger.info("NSC Import completed successfully.")
                    else:
                        self.logger.error(f"NSC Import failed: {res.stderr}")
                except Exception as e:
                    self.logger.error(f"NSC Import exception: {e}")
                finally:
                    self.active_operations["nsc"] = False
                    
            threading.Thread(target=run_importer, daemon=True).start()
            return {"success": True, "message": "NSC Refresh started"}
        except Exception as e:
            self.active_operations["nsc"] = False
            return {"success": False, "message": f"Failed to start NSC refresh: {e}"}

    def process_pans_now(self) -> Dict[str, Any]:
        if self.active_operations["pans_once"]:
            return {"success": False, "message": "PANS one-shot process is already running"}
            
        svc = self.service_controller.get_service_status("validation-pans-importer.service")
        if svc.get("status") == "RUNNING":
            return {"success": False, "message": "Cannot run 'Process Now' while live importer is RUNNING"}
            
        self.active_operations["pans_once"] = True
        if self.config_manager:
            self.config_manager._log_audit_event("DB_PANS_PROCESS_NOW", "SYSTEM", {"message": "Started PANS one-shot process"})
        try:
            cmd = self._importer_command(self.pans_importer_script, "--once")
            self.logger.info("Executing PANS Importer (One-shot)...")
            def run_importer():
                try:
                    subprocess.run(cmd, cwd=str(self.workspace_root), capture_output=True)
                finally:
                    self.active_operations["pans_once"] = False
                    
            threading.Thread(target=run_importer, daemon=True).start()
            return {"success": True, "message": "PANS one-shot processing started"}
        except Exception as e:
            self.active_operations["pans_once"] = False
            return {"success": False, "message": f"Failed to start PANS processing: {e}"}

    def clear_wrs(self) -> Dict[str, Any]:
        if not self.wrs_path.exists():
            return {"success": False, "message": "WRS Database file not found"}
        if self.active_operations["wrs"]:
            return {"success": False, "message": "Cannot clear while WRS refresh is running"}
            
        try:
            conn = sqlite3.connect(self.wrs_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wrs_%'")
            tables = [r[0] for r in cur.fetchall()]
            for table in tables:
                cur.execute(f"DROP TABLE {table}")
            
            # Reset tracking
            cur.execute("DELETE FROM import_batch")
            cur.execute("DELETE FROM import_file")
            conn.commit()
            conn.close()
            self.logger.info("WRS database cleared.")
            if self.config_manager:
                self.config_manager._log_audit_event("DB_WRS_CLEAR", "SYSTEM", {"message": "Cleared WRS database tables"})
            return {"success": True, "message": "WRS Database successfully cleared"}
        except Exception as e:
            self.logger.error(f"Error clearing WRS: {e}")
            return {"success": False, "message": f"Failed to clear WRS: {e}"}

    def clear_nsc(self) -> Dict[str, Any]:
        if not self.nsc_path.exists():
            return {"success": False, "message": "NSC Database file not found"}
        if self.active_operations["nsc"]:
            return {"success": False, "message": "Cannot clear while NSC refresh is running"}
            
        try:
            conn = sqlite3.connect(self.nsc_path)
            cur = conn.cursor()
            # Check if table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nsc_vessels'")
            if cur.fetchone():
                cur.execute("DELETE FROM nsc_vessels")
            
            cur.execute("DELETE FROM import_batch")
            cur.execute("DELETE FROM import_file")
            conn.commit()
            conn.close()
            self.logger.info("NSC database cleared.")
            if self.config_manager:
                self.config_manager._log_audit_event("DB_NSC_CLEAR", "SYSTEM", {"message": "Cleared NSC database tables"})
            return {"success": True, "message": "NSC Database successfully cleared"}
        except Exception as e:
            self.logger.error(f"Error clearing NSC: {e}")
            return {"success": False, "message": f"Failed to clear NSC: {e}"}

    def clear_pans(self) -> Dict[str, Any]:
        if not self.pans_path.exists():
            return {"success": False, "message": "PANS Database file not found"}
            
        svc = self.service_controller.get_service_status("validation-pans-importer.service")
        if svc.get("status") == "RUNNING" or self.active_operations["pans_once"]:
            return {"success": False, "message": "Cannot clear PANS while live importer is running. Please stop it first."}
            
        try:
            conn = sqlite3.connect(self.pans_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pans_%'")
            tables = [r[0] for r in cur.fetchall()]
            for table in tables:
                cur.execute(f"DROP TABLE {table}")
            
            cur.execute("DELETE FROM import_batch")
            cur.execute("DELETE FROM import_file")
            conn.commit()
            conn.close()
            self.logger.info("PANS database cleared.")
            if self.config_manager:
                self.config_manager._log_audit_event("DB_PANS_CLEAR", "SYSTEM", {"message": "Cleared PANS database tables"})
            return {"success": True, "message": "PANS Database successfully cleared"}
        except Exception as e:
            self.logger.error(f"Error clearing PANS: {e}")
            return {"success": False, "message": f"Failed to clear PANS: {e}"}
