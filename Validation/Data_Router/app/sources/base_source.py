"""Abstract base class for input sources."""

from abc import ABC, abstractmethod
import logging
from typing import Optional

from ..config.models import BaseSourceConfig, SourceType


class BaseSource(ABC):
    """Abstract interface implemented by all input ingest sources."""

    def __init__(self, config: BaseSourceConfig, logger: Optional[logging.Logger] = None):
        self.config = config
        self.name = config.name
        self.source_type: SourceType = config.type
        self.logger = logger or logging.getLogger("router")

    @abstractmethod
    def start(self) -> None:
        """Start the ingestion process."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the ingestion process gracefully."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if ingest worker is active."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if source feed/filesystem is accessible."""
        pass
