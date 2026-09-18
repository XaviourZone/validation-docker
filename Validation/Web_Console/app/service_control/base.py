"""Abstract base class for operating system service management."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple


class BaseServiceController(ABC):
    """Abstract interface defining service lifecycle management."""

    @abstractmethod
    def start(self, service_name: str) -> Tuple[bool, str]:
        """Start the given service."""
        pass

    @abstractmethod
    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stop the given service."""
        pass

    @abstractmethod
    def restart(self, service_name: str) -> Tuple[bool, str]:
        """Restart the given service."""
        pass

    @abstractmethod
    def reload(self, service_name: str) -> Tuple[bool, str]:
        """Reload configuration for the given service."""
        pass

    @abstractmethod
    def validate_config(self, config_path: str) -> Tuple[bool, str]:
        """Validate configuration syntax and semantics."""
        pass

    @abstractmethod
    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Return status dictionary (status: RUNNING, STOPPED, ERROR, etc.)."""
        pass

    def start_service(self, service_name: str) -> Dict[str, Any]:
        """Convenience wrapper returning structured dict."""
        success, msg = self.start(service_name)
        return {"success": success, "message": msg, "service": service_name}

    def stop_service(self, service_name: str) -> Dict[str, Any]:
        """Convenience wrapper returning structured dict."""
        success, msg = self.stop(service_name)
        return {"success": success, "message": msg, "service": service_name}

    def restart_service(self, service_name: str) -> Dict[str, Any]:
        """Convenience wrapper returning structured dict."""
        success, msg = self.restart(service_name)
        return {"success": success, "message": msg, "service": service_name}

    def reload_configuration(self, service_name: str) -> Dict[str, Any]:
        """Convenience wrapper returning structured dict."""
        success, msg = self.reload(service_name)
        return {"success": success, "message": msg, "service": service_name}
