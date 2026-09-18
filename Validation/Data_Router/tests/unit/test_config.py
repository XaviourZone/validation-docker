"""Unit tests for configuration loading, parsing, and validation."""

import unittest
from pathlib import Path
import tempfile
import yaml

from Validation.Data_Router.app.config.loader import (
    ConfigurationError,
    load_config,
    parse_raw_dict,
    validate_config,
)
from Validation.Data_Router.app.config.models import SourceType, FramingType


class TestConfiguration(unittest.TestCase):
    """Test suite for configuration loader and validator."""

    def setUp(self):
        self.valid_raw = {
            "data_inflow": {"base_dir": "DATA_INFLOW"},
            "parser_destinations": {
                "SAIS": {"host": "127.0.0.1", "port": 10001, "framing": "ndjson"},
                "MSIS": {"host": "127.0.0.1", "port": 10002, "framing": "ndjson"},
            },
            "sources": {
                "SAIS_IOR": {
                    "type": "file",
                    "folder": "SAIS_IOR",
                    "parser": "SAIS",
                    "enabled": True,
                },
                "VATMS_EAST": {
                    "type": "tcp",
                    "remote_host": "127.0.0.1",
                    "remote_port": 20001,
                    "parser": "SAIS",
                    "enabled": True,
                    "framing": "line",
                }
            },
            "retry": {
                "max_attempts": 3,
                "initial_delay_seconds": 1.0,
                "max_delay_seconds": 10.0,
                "backoff_multiplier": 2.0,
            },
            "queue": {
                "max_size": 500,
                "worker_count": 2,
                "high_watermark_ratio": 0.8,
            },
            "monitoring": {
                "enabled": True,
                "http_host": "127.0.0.1",
                "http_port": 8081,
            },
            "state": {"db_path": "state/test_state.db"},
        }

    def test_parse_valid_configuration(self):
        cfg = parse_raw_dict(self.valid_raw)
        self.assertEqual(cfg.data_inflow.base_dir, "DATA_INFLOW")
        self.assertIn("SAIS", cfg.parser_destinations)
        self.assertEqual(cfg.parser_destinations["SAIS"].port, 10001)
        self.assertEqual(cfg.sources["SAIS_IOR"].type, SourceType.FILE)
        self.assertEqual(cfg.sources["VATMS_EAST"].framing, FramingType.LINE)

    def test_validate_valid_config_returns_no_errors(self):
        cfg = parse_raw_dict(self.valid_raw)
        errors = validate_config(cfg)
        self.assertEqual(len(errors), 0, f"Unexpected validation errors: {errors}")

    def test_invalid_port_detected(self):
        raw = dict(self.valid_raw)
        raw["parser_destinations"] = {
            "SAIS": {"host": "127.0.0.1", "port": 99999}
        }
        cfg = parse_raw_dict(raw)
        errors = validate_config(cfg)
        self.assertTrue(any("invalid port" in e for e in errors))

    def test_unknown_parser_in_source_detected(self):
        raw = dict(self.valid_raw)
        raw["sources"]["SAIS_IOR"]["parser"] = "NON_EXISTENT_PARSER"
        cfg = parse_raw_dict(raw)
        errors = validate_config(cfg)
        self.assertTrue(any("does not exist in 'parser_destinations'" in e for e in errors))

    def test_load_config_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
            yaml.dump(self.valid_raw, tf)
            tf_path = Path(tf.name)

        try:
            cfg = load_config(tf_path)
            self.assertEqual(cfg.queue.max_size, 500)
        finally:
            if tf_path.exists():
                tf_path.unlink()


if __name__ == "__main__":
    unittest.main()
