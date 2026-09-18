"""Factory for selecting and instantiating service controllers."""

import os
import platform
from pathlib import Path
from typing import Optional

from .base import BaseServiceController
from .linux import LinuxSystemdController
from .windows import WindowsDevelopmentController


class NoopServiceController(BaseServiceController):
    """Docker-safe controller: lifecycle is managed by Docker Compose, not systemd."""
    def __init__(self, workspace_root=None):
        self.workspace_root = workspace_root

    def start(self, service_name):
        return False, "Service lifecycle is managed by Docker Compose."

    def stop(self, service_name):
        return False, "Service lifecycle is managed by Docker Compose."

    def restart(self, service_name):
        return False, "Service lifecycle is managed by Docker Compose."

    def reload(self, service_name):
        return False, "Service lifecycle is managed by Docker Compose."

    def validate_config(self, config_path):
        return True, "Configuration validation is available through the application."

    def get_service_status(self, service_name):
        return {"status": "EXTERNAL", "service": service_name, "message": "Managed by Docker Compose"}


def get_service_controller(
    mode: str = "auto",
    workspace_root: Optional[Path] = None,
) -> BaseServiceController:
    """Return appropriate ServiceController based on mode or host platform."""
    selected_mode = mode.lower()
    
    if selected_mode == "none":
        return NoopServiceController(workspace_root)
    if selected_mode == "systemd":
        return LinuxSystemdController(workspace_root)
    elif selected_mode == "windows":
        return WindowsDevelopmentController(workspace_root)
    elif selected_mode == "auto":
        # Autodetect OS
        if platform.system().lower() == "windows":
            return WindowsDevelopmentController(workspace_root)
        else:
            return LinuxSystemdController(workspace_root)
    else:
        raise ValueError(f"Unknown service control mode: '{mode}'. Expected 'auto', 'windows', 'systemd', or 'none'.")
