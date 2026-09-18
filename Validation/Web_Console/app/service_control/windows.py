"""Windows Development Service Controller.

Provides development-safe process inspection and controlled local commands
without simulating or attempting Linux systemd actions on Windows.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseServiceController


class WindowsDevelopmentController(BaseServiceController):
    """Controls background Validation services in Windows development environments."""

    SERVICE_COMMANDS = {
        "router": ([sys.executable, "-m", "Validation.Data_Router.app.main", "--config", "Validation/Data_Router/config/sources.yaml"], "Validation.Data_Router.app.main"),
        "parser": ([sys.executable, "-m", "Validation.Data_Parser.app.main", "--config", "Validation/Data_Parser/config/parser.yaml"], "Validation.Data_Parser.app.main"),
        "forwarder": ([sys.executable, "-m", "Validation.Data_Forwarder.app.main", "--config", "Validation/Data_Forwarder/config/forwarder.yaml"], "Validation.Data_Forwarder.app.main"),
        "pans": ([sys.executable, "Validation/Database/PANS/importer/pans_importer.py", "--config", "Validation/Database/config/database.yaml"], "pans_importer.py"),
    }

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd()

    @staticmethod
    def _kind(service_name: str) -> Optional[str]:
        name = service_name.lower()
        for kind in ("router", "parser", "forwarder", "pans"):
            if kind in name:
                return kind
        return None

    def _launch(self, kind: str) -> Tuple[bool, str]:
        command, _ = self.SERVICE_COMMANDS[kind]
        if self.get_service_status(f"validation-{kind}.service")["status"] == "RUNNING":
            return True, f"{kind.title()} service is already running"
        try:
            kwargs = {"cwd": str(self.workspace_root), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(command, **kwargs)
            return True, f"{kind.title()} service launched in background development process"
        except Exception as exc:
            return False, f"Failed to start {kind.title()} service: {exc}"

    def start(self, service_name: str) -> Tuple[bool, str]:
        kind = self._kind(service_name)
        return self._launch(kind) if kind else (False, f"Service '{service_name}' is not configured for Windows development")

    def stop(self, service_name: str) -> Tuple[bool, str]:
        import psutil
        kind = self._kind(service_name)
        if not kind:
            return False, f"Service '{service_name}' is not configured for Windows development"
        token = self.SERVICE_COMMANDS[kind][1]
        stopped = False
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if proc.pid == os.getpid():
                    continue
                if token in " ".join(proc.info.get("cmdline") or []):
                    proc.terminate()
                    try:
                        proc.wait(timeout=3.0)
                    except psutil.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
                    stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                continue
        return (True, f"Service '{service_name}' stopped successfully") if stopped else (False, f"Service '{service_name}' was not running")

    def restart(self, service_name: str) -> Tuple[bool, str]:
        self.stop(service_name)
        time.sleep(0.5)
        return self.start(service_name)

    def reload(self, service_name: str) -> Tuple[bool, str]:
        return self.restart(service_name)

    def validate_config(self, config_path: str) -> Tuple[bool, str]:
        full_path = self.workspace_root / config_path if not Path(config_path).is_absolute() else Path(config_path)
        if not full_path.exists():
            return False, f"Configuration file does not exist: {full_path}"
        try:
            from Validation.Data_Router.app.config.loader import load_config
            load_config(full_path)
            return True, "Configuration syntax and semantic checks PASSED"
        except Exception as exc:
            return False, f"Configuration validation FAILED: {exc}"

    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        import psutil
        kind = self._kind(service_name)
        token = self.SERVICE_COMMANDS[kind][1] if kind else service_name
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if proc.pid != os.getpid() and token in " ".join(proc.info.get("cmdline") or []):
                    return {"service": service_name, "status": "RUNNING", "pid": str(proc.pid), "controller": "WindowsDevelopmentController", "mode": "windows_development"}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"service": service_name, "status": "STOPPED", "pid": None, "controller": "WindowsDevelopmentController", "mode": "windows_development"}
