"""Factory for selecting and instantiating service controllers."""

import os
import platform
from pathlib import Path
from typing import Optional

from .base import BaseServiceController
from .linux import LinuxSystemdController
from .windows import WindowsDevelopmentController


def get_service_controller(
    mode: str = "auto",
    workspace_root: Optional[Path] = None,
) -> BaseServiceController:
    """Return appropriate ServiceController based on mode or host platform."""
    selected_mode = mode.lower()
    
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
        raise ValueError(f"Unknown service control mode: '{mode}'. Expected 'auto', 'windows', or 'systemd'.")
