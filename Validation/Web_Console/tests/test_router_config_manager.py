"""Automated tests for RouterConfigManager covering validation, atomic writes, concurrency, and safety."""

import copy
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import yaml

from Validation.Web_Console.app.config_manager import RouterConfigManager


class TestRouterConfigManager(unittest.TestCase):
    """Test suite covering all operational scenarios for RouterConfigManager."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_cfg_mgr_")
        self.workspace_root = Path(self.temp_dir)
        self.config_path = self.workspace_root / "sources.yaml"

        # Create valid base sources.yaml
        self.base_cfg = {
            "data_inflow": {"base_dir": "DATA_INFLOW"},
            "parser_destinations": {
                "SAIS": {"host": "127.0.0.1", "port": 10001, "framing": "ndjson"},
                "MSIS": {"host": "127.0.0.1", "port": 10002, "framing": "ndjson"},
                "LRIT": {"host": "127.0.0.1", "port": 10003, "framing": "ndjson"},
                "VATMS": {"host": "127.0.0.1", "port": 10004, "framing": "ndjson"},
                "NAIS": {"host": "127.0.0.1", "port": 10005, "framing": "ndjson"},
            },
            "sources": {
                "SAIS_IOR": {
                    "type": "file",
                    "folder": "SAIS_IOR",
                    "parser": "SAIS",
                    "enabled": True,
                    "poll_interval_seconds": 1.0,
                    "stability_window_seconds": 1.0,
                    "file_patterns": ["*.csv", "*.txt", "*"],
                    "preserve_file": True,
                },
                "VATMS_EAST": {
                    "type": "tcp",
                    "remote_host": "127.0.0.1",
                    "remote_port": 20001,
                    "parser": "VATMS",
                    "enabled": True,
                    "framing": "line",
                    "delimiter": "\n",
                    "max_line_length": 65536,
                    "reconnect_initial_delay": 2.0,
                    "reconnect_max_delay": 60.0,
                    "reconnect_multiplier": 2.0,
                },
            },
            "retry": {
                "max_attempts": 5,
                "initial_delay_seconds": 2.0,
                "max_delay_seconds": 60.0,
                "backoff_multiplier": 2.0,
            },
            "queue": {
                "max_size": 10000,
                "worker_count": 4,
                "high_watermark_ratio": 0.8,
            },
            "monitoring": {
                "enabled": True,
                "http_host": "127.0.0.1",
                "http_port": 8080,
            },
            "state": {
                "db_path": "state/router_state.db",
            },
        }

        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_cfg, f)

        self.mgr = RouterConfigManager(config_path=self.config_path, workspace_root=self.workspace_root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_get_raw_config_and_destinations(self):
        cfg = self.mgr.get_raw_config()
        self.assertIn("parser_destinations", cfg)
        self.assertIn("sources", cfg)

        dests = self.mgr.get_parser_destinations()
        self.assertEqual(len(dests), 5)
        self.assertIn("SAIS", dests)
        self.assertEqual(dests["SAIS"]["port"], 10001)

    def test_02_add_file_source_valid(self):
        payload = {
            "source_name": "SAIS_NORTH",
            "type": "file",
            "parser": "SAIS",
            "enabled": True,
            "folder": "SAIS_NORTH",
            "file_patterns": ["*.csv", "*.txt"],
            "stability_window_seconds": 1.5,
            "poll_interval_seconds": 0.5,
        }
        is_valid, errors, normalized = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertTrue(is_valid, f"Errors: {errors}")
        self.assertEqual(len(errors), 0)

        success, msg, norm = self.mgr.save_source(payload, is_new=True)
        self.assertTrue(success)
        self.assertIn("successfully added", msg)

        # Verify saved in file
        sources = self.mgr.get_sources()
        self.assertIn("SAIS_NORTH", sources)
        self.assertEqual(sources["SAIS_NORTH"]["folder"], "SAIS_NORTH")
        self.assertEqual(sources["SAIS_NORTH"]["poll_interval_seconds"], 0.5)

    def test_03_add_tcp_source_valid(self):
        payload = {
            "source_name": "VATMS_NORTH",
            "type": "tcp",
            "parser": "VATMS",
            "enabled": True,
            "remote_host": "192.168.1.50",
            "remote_port": 20005,
            "framing": "line",
            "max_line_length": 32768,
            "reconnect_initial_delay": 1.0,
            "reconnect_max_delay": 30.0,
        }
        is_valid, errors, normalized = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertTrue(is_valid, f"Errors: {errors}")

        success, msg, norm = self.mgr.save_source(payload, is_new=True)
        self.assertTrue(success)

        sources = self.mgr.get_sources()
        self.assertIn("VATMS_NORTH", sources)
        self.assertEqual(sources["VATMS_NORTH"]["remote_port"], 20005)

    def test_04_missing_required_fields(self):
        payload = {"type": "file"}
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("Source Name is required" in e for e in errors))
        self.assertTrue(any("Parser Mapping is required" in e for e in errors))

    def test_05_invalid_tcp_port(self):
        payload = {
            "source_name": "TCP_BAD_PORT",
            "type": "tcp",
            "parser": "VATMS",
            "enabled": True,
            "remote_host": "127.0.0.1",
            "remote_port": 999999,  # Out of range
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("Remote Port must be between 1 and 65535" in e for e in errors))

    def test_06_invalid_parser_mapping(self):
        payload = {
            "source_name": "SAIS_UNKNOWN_PARSER",
            "type": "file",
            "parser": "NON_EXISTENT_PARSER",
            "enabled": True,
            "folder": "TEST",
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("is not configured" in e for e in errors))

    def test_07_duplicate_source_name(self):
        payload = {
            "source_name": "SAIS_IOR",  # Already exists in setUp
            "type": "file",
            "parser": "SAIS",
            "folder": "DUP",
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("already exists" in e for e in errors))

    def test_08_edit_existing_source(self):
        payload = {
            "source_name": "SAIS_IOR",
            "type": "file",
            "parser": "SAIS",
            "enabled": False,
            "folder": "SAIS_IOR_RENAMED",
            "file_patterns": ["*.csv"],
            "stability_window_seconds": 3.0,
            "poll_interval_seconds": 2.0,
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=False)
        self.assertTrue(is_valid, f"Errors: {errors}")

        success, msg, _ = self.mgr.save_source(payload, is_new=False)
        self.assertTrue(success)
        self.assertIn("successfully updated", msg)

        sources = self.mgr.get_sources()
        self.assertEqual(sources["SAIS_IOR"]["folder"], "SAIS_IOR_RENAMED")
        self.assertFalse(sources["SAIS_IOR"]["enabled"])
        self.assertEqual(sources["SAIS_IOR"]["stability_window_seconds"], 3.0)

    def test_09_atomic_save_and_backup_creation(self):
        payload = {
            "source_name": "LRIT_NEW",
            "type": "file",
            "parser": "LRIT",
            "enabled": True,
            "folder": "LRIT_NEW",
        }
        success, msg, _ = self.mgr.save_source(payload, is_new=True)
        self.assertTrue(success)

        # Verify backup exists
        self.assertTrue(self.mgr.backup_path.exists())
        # Temp file must have been cleaned up
        self.assertFalse(self.mgr.tmp_path.exists())

    def test_10_configuration_validation_failure_no_corrupt(self):
        invalid_payload = {
            "source_name": "BAD_SRC",
            "type": "file",
            "parser": "UNKNOWN",
        }
        success, msg, _ = self.mgr.save_source(invalid_payload, is_new=True)
        self.assertFalse(success)

        # Ensure config file was not altered
        sources = self.mgr.get_sources()
        self.assertNotIn("BAD_SRC", sources)

    def test_11_enable_and_disable_source(self):
        # Disable SAIS_IOR
        success, msg = self.mgr.toggle_source("SAIS_IOR", False)
        self.assertTrue(success)
        self.assertFalse(self.mgr.get_sources()["SAIS_IOR"]["enabled"])

        # Enable SAIS_IOR
        success, msg = self.mgr.toggle_source("SAIS_IOR", True)
        self.assertTrue(success)
        self.assertTrue(self.mgr.get_sources()["SAIS_IOR"]["enabled"])

    def test_12_delete_source_safe(self):
        # Delete VATMS_EAST
        success, msg = self.mgr.delete_source("VATMS_EAST")
        self.assertTrue(success)
        self.assertNotIn("VATMS_EAST", self.mgr.get_sources())
        self.assertIn("deleted from configuration", msg)

    def test_13_file_specific_field_validation(self):
        # Negative stability window
        payload = {
            "source_name": "FILE_NEG",
            "type": "file",
            "parser": "SAIS",
            "folder": "TEST",
            "stability_window_seconds": -1.0,
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("Stability Window must be greater than 0" in e for e in errors))

    def test_14_tcp_specific_field_validation(self):
        # Incomplete TCP parameters (missing remote_host)
        payload = {
            "source_name": "TCP_NO_HOST",
            "type": "tcp",
            "parser": "VATMS",
            "remote_host": "",
            "remote_port": 20001,
        }
        is_valid, errors, _ = self.mgr.validate_source_payload(payload, is_new=True)
        self.assertFalse(is_valid)
        self.assertTrue(any("non-empty 'remote_host'" in e for e in errors))

    def test_15_configuration_concurrency_lock(self):
        """Simulate concurrent threads writing configuration."""
        success_list = []

        def worker(idx):
            payload = {
                "source_name": f"SRC_CONCURRENT_{idx}",
                "type": "file",
                "parser": "SAIS",
                "folder": f"FOLDER_{idx}",
            }
            success, _, _ = self.mgr.save_source(payload, is_new=True)
            success_list.append(success)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(success_list), 5)
        self.assertTrue(all(success_list))
        sources = self.mgr.get_sources()
        for i in range(5):
            self.assertIn(f"SRC_CONCURRENT_{i}", sources)

    def test_16_audit_logging(self):
        payload = {
            "source_name": "AUDIT_SRC",
            "type": "file",
            "parser": "SAIS",
            "folder": "AUDIT",
        }
        self.mgr.save_source(payload, is_new=True)
        self.mgr.toggle_source("AUDIT_SRC", False)
        self.mgr.delete_source("AUDIT_SRC")

        audit_log = self.mgr.get_audit_log()
        self.assertGreaterEqual(len(audit_log), 3)
        events = [e["event"] for e in audit_log]
        self.assertIn("CONFIG_SOURCE_ADDED", events)
        self.assertIn("CONFIG_SOURCE_DISABLED", events)
        self.assertIn("CONFIG_SOURCE_DELETED", events)


if __name__ == "__main__":
    unittest.main()
