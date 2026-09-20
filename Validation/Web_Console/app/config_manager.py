"""Safe, concurrent, atomic configuration manager for Data Router sources.yaml."""

import copy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Dict, List, Optional, Tuple
import yaml

from Validation.Data_Router.app.config.loader import ConfigurationError, load_config, parse_raw_dict, validate_config


class RouterConfigManager:
    """Manages reading, semantic validation, atomic persistence, and auditing for sources.yaml."""

    def __init__(
        self,
        config_path: Path,
        workspace_root: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.workspace_root = workspace_root or Path.cwd()
        self.config_path = config_path if config_path.is_absolute() else self.workspace_root / config_path
        self.backup_path = self.config_path.with_suffix(".yaml.bak")
        self.tmp_path = self.config_path.with_suffix(".yaml.tmp")
        self.logger = logger or logging.getLogger("web_console")
        self._lock = threading.RLock()
        self._audit_log: List[Dict[str, Any]] = []

    def get_raw_config(self) -> Dict[str, Any]:
        """Read and return current raw YAML config dict."""
        with self._lock:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

    def get_parser_destinations(self) -> Dict[str, Dict[str, Any]]:
        """Return configured parser destinations dictionary."""
        cfg = self.get_raw_config()
        return cfg.get("parser_destinations", {})

    def get_sources(self) -> Dict[str, Dict[str, Any]]:
        """Return configured sources dictionary."""
        cfg = self.get_raw_config()
        return cfg.get("sources", {})

    def validate_source_payload(
        self,
        payload: Dict[str, Any],
        is_new: bool = False,
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """Validate input parameters for a source without modifying configuration.
        
        Returns:
            (is_valid, error_list, normalized_source_dict)
        """
        errors: List[str] = []
        if not isinstance(payload, dict):
            return False, ["Payload must be a JSON dictionary"], {}

        raw_cfg = self.get_raw_config()
        sources = raw_cfg.get("sources", {})
        destinations = raw_cfg.get("parser_destinations", {})

        # 1. Source Name Validation
        source_name = str(payload.get("source_name") or payload.get("name") or "").strip()
        if not source_name:
            errors.append("Source Name is required.")
        elif not re.match(r"^[A-Za-z0-9_]+$", source_name):
            errors.append(f"Source Name '{source_name}' contains invalid characters. Use alphanumeric characters and underscores only.")
        elif is_new and source_name in sources:
            errors.append(f"Source Name '{source_name}' already exists. Choose a unique name or edit the existing source.")
        elif not is_new and source_name not in sources:
            errors.append(f"Source '{source_name}' does not exist in configuration.")

        # 2. Type Validation
        stype = str(payload.get("type") or "").strip().lower()
        if stype not in ("file", "tcp"):
            errors.append(f"Invalid input type '{stype}'. Expected 'file' or 'tcp'.")

        # 3. Parser Mapping Validation
        parser_name = str(payload.get("parser") or "").strip()
        if not parser_name:
            errors.append("Parser Mapping is required.")
        elif parser_name not in destinations:
            valid_parsers = ", ".join(destinations.keys())
            errors.append(f"Parser '{parser_name}' is not configured. Valid destinations: {valid_parsers}")

        # 4. Enabled Flag
        enabled = bool(payload.get("enabled", True))

        # Build clean source configuration
        normalized: Dict[str, Any] = {
            "type": stype,
            "parser": parser_name,
            "enabled": enabled,
        }

        # Optional Description (stored in comment/meta if present)
        description = payload.get("description")
        if description:
            normalized["description"] = str(description).strip()

        # 5. Type-Specific Validation
        if stype == "file":
            folder = str(payload.get("folder") or "").strip()
            if not folder:
                errors.append("FILE source requires a non-empty 'folder' path.")
            normalized["folder"] = folder

            # Stability Window
            try:
                stability = float(payload.get("stability_window_seconds", 1.0))
                if stability <= 0:
                    errors.append("Stability Window must be greater than 0 seconds.")
                normalized["stability_window_seconds"] = stability
            except (ValueError, TypeError):
                errors.append("Stability Window must be a valid positive number.")

            # Polling Interval
            try:
                poll = float(payload.get("poll_interval_seconds", 1.0))
                if poll <= 0:
                    errors.append("Polling Interval must be greater than 0 seconds.")
                normalized["poll_interval_seconds"] = poll
            except (ValueError, TypeError):
                errors.append("Polling Interval must be a valid positive number.")

            # File Patterns
            raw_patterns = payload.get("file_patterns", ["*.csv", "*.txt", "*"])
            if isinstance(raw_patterns, str):
                patterns = [p.strip() for p in raw_patterns.split(",") if p.strip()]
            elif isinstance(raw_patterns, list):
                patterns = [str(p).strip() for p in raw_patterns if str(p).strip()]
            else:
                patterns = ["*.csv", "*.txt", "*"]

            if not patterns:
                errors.append("FILE source requires at least one file pattern.")
            normalized["file_patterns"] = patterns
            normalized["preserve_file"] = bool(payload.get("preserve_file", True))

        elif stype == "tcp":
            remote_host = str(payload.get("remote_host") or "").strip()
            if not remote_host:
                errors.append("TCP source requires a non-empty 'remote_host'.")
            normalized["remote_host"] = remote_host

            try:
                remote_port = int(payload.get("remote_port", 0))
                if not (1 <= remote_port <= 65535):
                    errors.append(f"TCP Remote Port must be between 1 and 65535 (got {remote_port}).")
                normalized["remote_port"] = remote_port
            except (ValueError, TypeError):
                errors.append("TCP Remote Port must be a valid integer.")

            framing = str(payload.get("framing") or "line").strip().lower()
            if framing not in ("line", "delimited"):
                framing = "line"
            normalized["framing"] = framing
            normalized["delimiter"] = str(payload.get("delimiter") or "\n")

            try:
                max_line = int(payload.get("max_line_length", 65536))
                if max_line < 128:
                    errors.append("TCP max_line_length must be at least 128 bytes.")
                normalized["max_line_length"] = max_line
            except (ValueError, TypeError):
                errors.append("TCP max_line_length must be a valid integer.")

            # Reconnect Settings
            try:
                init_delay = float(payload.get("reconnect_initial_delay", 2.0))
                max_delay = float(payload.get("reconnect_max_delay", 60.0))
                multiplier = float(payload.get("reconnect_multiplier", 2.0))
                if init_delay <= 0 or max_delay < init_delay or multiplier < 1.0:
                    errors.append("Invalid reconnect settings: ensure initial > 0, max >= initial, and multiplier >= 1.0.")
                normalized["reconnect_initial_delay"] = init_delay
                normalized["reconnect_max_delay"] = max_delay
                normalized["reconnect_multiplier"] = multiplier
            except (ValueError, TypeError):
                errors.append("Reconnect settings must be valid numbers.")

        # 6. Global Semantic Validation Dry-Run
        if not errors:
            simulated_cfg = copy.deepcopy(raw_cfg)
            if "sources" not in simulated_cfg:
                simulated_cfg["sources"] = {}
            simulated_cfg["sources"][source_name] = normalized
            try:
                parsed = parse_raw_dict(simulated_cfg)
                semantic_errors = validate_config(parsed)
                if semantic_errors:
                    errors.extend(semantic_errors)
            except Exception as e:
                errors.append(f"Semantic configuration error: {str(e)}")

        return (len(errors) == 0), errors, normalized

    def save_source(
        self,
        payload: Dict[str, Any],
        is_new: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Atomically validate, backup, and save a source configuration."""
        with self._lock:
            is_valid, errors, normalized = self.validate_source_payload(payload, is_new=is_new)
            if not is_valid:
                return False, f"Validation failed: {'; '.join(errors)}", {}

            source_name = str(payload.get("source_name") or payload.get("name")).strip()
            raw_cfg = self._read_raw_unlocked()
            if "sources" not in raw_cfg:
                raw_cfg["sources"] = {}

            old_source = raw_cfg["sources"].get(source_name)
            raw_cfg["sources"][source_name] = normalized

            # Perform atomic write with backup
            try:
                self._atomic_write_unlocked(raw_cfg)
            except Exception as e:
                self.logger.error(f"Failed to atomically write configuration: {e}")
                return False, f"Configuration write failed: {str(e)}", {}

            # Audit event
            event_type = "CONFIG_SOURCE_ADDED" if is_new or old_source is None else "CONFIG_SOURCE_UPDATED"
            self._log_audit_event(
                event=event_type,
                source=source_name,
                details={"type": normalized.get("type"), "parser": normalized.get("parser"), "enabled": normalized.get("enabled")}
            )

            msg = f"Source '{source_name}' successfully {'added' if is_new else 'updated'}. Reload required to apply changes to running Router."
            return True, msg, normalized

    def rename_source(self, old_source_name: str, new_source_name: str) -> Tuple[bool, str]:
        """Rename a source ID while preserving its complete source configuration."""
        with self._lock:
            old_name = str(old_source_name or "").strip()
            new_name = str(new_source_name or "").strip()
            raw_cfg = self._read_raw_unlocked()
            sources = raw_cfg.get("sources", {})
            if old_name not in sources:
                return False, f"Source '{old_name}' not found in configuration."
            if not re.match(r"^[A-Za-z0-9_]+$", new_name):
                return False, "Source ID contains invalid characters. Use alphanumeric characters and underscores only."
            if not new_name:
                return False, "Source ID is required."
            if new_name in sources and new_name != old_name:
                return False, f"Source ID '{new_name}' already exists."

            renamed = copy.deepcopy(sources[old_name])
            raw_cfg["sources"] = {k: v for k, v in sources.items() if k != old_name}
            raw_cfg["sources"][new_name] = renamed

            try:
                parsed = parse_raw_dict(raw_cfg)
                errors = validate_config(parsed)
                if errors:
                    return False, f"Cannot rename source: {'; '.join(errors)}"
                self._atomic_write_unlocked(raw_cfg)
            except Exception as e:
                return False, f"Failed to rename source '{old_name}': {str(e)}"

            self._log_audit_event(
                event="CONFIG_SOURCE_RENAMED",
                source=new_name,
                details={"old_source": old_name, "new_source": new_name},
            )
            return True, f"Source ID changed from '{old_name}' to '{new_name}'."

    def delete_source(self, source_name: str) -> Tuple[bool, str]:
        """Safely delete a source from sources.yaml with validation and atomic backup."""
        with self._lock:
            raw_cfg = self._read_raw_unlocked()
            sources = raw_cfg.get("sources", {})
            if source_name not in sources:
                return False, f"Source '{source_name}' not found in configuration."

            # Ensure deleting does not break whole config
            test_cfg = copy.deepcopy(raw_cfg)
            del test_cfg["sources"][source_name]
            try:
                parsed = parse_raw_dict(test_cfg)
                sem_errors = validate_config(parsed)
                if sem_errors:
                    return False, f"Cannot delete '{source_name}': {'; '.join(sem_errors)}"
            except Exception as e:
                return False, f"Cannot delete '{source_name}': {str(e)}"

            # Remove and write atomically
            del raw_cfg["sources"][source_name]
            try:
                self._atomic_write_unlocked(raw_cfg)
            except Exception as e:
                return False, f"Failed to save configuration after deletion: {str(e)}"

            self._log_audit_event(
                event="CONFIG_SOURCE_DELETED",
                source=source_name,
                details={"deleted_at": datetime.now(timezone.utc).isoformat()}
            )
            return True, f"Source '{source_name}' deleted from configuration. Reload required to stop routing."

    def toggle_source(self, source_name: str, enable: bool) -> Tuple[bool, str]:
        """Safely toggle enabled state of a source with atomic backup and audit."""
        with self._lock:
            raw_cfg = self._read_raw_unlocked()
            sources = raw_cfg.get("sources", {})
            if source_name not in sources:
                return False, f"Source '{source_name}' not found in configuration."

            current = sources[source_name].get("enabled", True)
            if current == enable:
                state_str = "already enabled" if enable else "already disabled"
                return True, f"Source '{source_name}' is {state_str}."

            sources[source_name]["enabled"] = enable
            raw_cfg["sources"] = sources

            try:
                self._atomic_write_unlocked(raw_cfg)
            except Exception as e:
                return False, f"Failed to toggle source '{source_name}': {str(e)}"

            event_type = "CONFIG_SOURCE_ENABLED" if enable else "CONFIG_SOURCE_DISABLED"
            self._log_audit_event(event=event_type, source=source_name, details={"enabled": enable})

            action_str = "enabled" if enable else "disabled"
            return True, f"Source '{source_name}' {action_str} in configuration. Reload required to apply."

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent configuration audit events."""
        with self._lock:
            return list(reversed(self._audit_log[-limit:]))

    def _read_raw_unlocked(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _atomic_write_unlocked(self, data: Dict[str, Any]) -> None:
        """Write configuration atomically using a temporary file and creating a backup."""
        # 1. Write to temporary file
        with open(self.tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        # 2. Validate temporary file parses and loads correctly
        try:
            load_config(self.tmp_path)
        except Exception as e:
            if self.tmp_path.exists():
                self.tmp_path.unlink()
            raise ConfigurationError(f"Generated configuration is invalid: {e}")

        # 3. Create backup of current configuration if it exists
        if self.config_path.exists():
            shutil.copy2(self.config_path, self.backup_path)

        # 4. Atomically replace active file with temporary file
        os.replace(self.tmp_path, self.config_path)

    def _log_audit_event(self, event: str, source: str, details: Optional[Dict[str, Any]] = None) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "event": event,
            "source": source,
            "details": details or {},
        }
        self._audit_log.append(entry)
        self.logger.info(f"[AUDIT] {event} source={source} details={details}")
