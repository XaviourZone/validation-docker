"""Linux Systemd Service Controller for Ubuntu Production."""

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseServiceController


class LinuxSystemdController(BaseServiceController):
    """Controls background systemd services on Ubuntu/Linux."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd()

    def start(self, service_name: str) -> Tuple[bool, str]:
        """Start systemd unit."""
        return self._run_systemctl(["start", service_name])

    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stop systemd unit."""
        return self._run_systemctl(["stop", service_name])

    def restart(self, service_name: str) -> Tuple[bool, str]:
        """Restart systemd unit."""
        return self._run_systemctl(["restart", service_name])

    def reload(self, service_name: str) -> Tuple[bool, str]:
        """Reload systemd unit."""
        return self._run_systemctl(["reload-or-restart", service_name])

    def validate_config(self, config_path: str) -> Tuple[bool, str]:
        """Validate configuration syntax and semantics."""
        full_path = self.workspace_root / config_path if not Path(config_path).is_absolute() else Path(config_path)
        if not full_path.exists():
            return False, f"Configuration file does not exist: {full_path}"

        try:
            from Validation.Data_Router.app.config.loader import load_config
            load_config(full_path)
            return True, "Configuration syntax and semantic checks PASSED"
        except Exception as e:
            return False, f"Configuration validation FAILED: {e}"

    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Query systemd unit state."""
        try:
            # Query systemctl show to get structured properties
            res = subprocess.run(
                ["systemctl", "show", service_name, "--property=ActiveState,SubState,MainPID"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3.0,
            )
            props = {}
            for line in res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()

            active_state = props.get("ActiveState", "").lower()
            if not active_state:
                res_simple = subprocess.run(
                    ["systemctl", "is-active", service_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3.0,
                )
                active_state = res_simple.stdout.strip().lower()

            if active_state == "active":
                status = "RUNNING"
            elif active_state in ("inactive", "failed"):
                status = "STOPPED"
            elif active_state == "activating":
                status = "STARTING"
            elif active_state == "deactivating":
                status = "STOPPING"
            else:
                status = active_state.upper() or "UNKNOWN"

            pid_str = props.get("MainPID", "0")
            pid_val = int(pid_str) if pid_str.isdigit() and int(pid_str) > 0 else None

            return {
                "service": service_name,
                "status": status,
                "pid": pid_val,
                "systemd_state": active_state,
                "controller": "LinuxSystemdController",
                "mode": "linux_systemd"
            }
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return {
                "service": service_name,
                "status": "UNKNOWN",
                "pid": None,
                "error": str(e),
                "controller": "LinuxSystemdController",
                "mode": "linux_systemd"
            }

    def _run_systemctl(self, args: list) -> Tuple[bool, str]:
        cmd = ["systemctl"] + args
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
            )
            if res.returncode == 0:
                return True, f"Command 'systemctl {' '.join(args)}' succeeded"
            err = res.stderr.strip() or res.stdout.strip() or f"Exited with code {res.returncode}"
            return False, f"systemctl error: {err}"
        except Exception as e:
            return False, f"Failed to execute systemctl: {e}"
