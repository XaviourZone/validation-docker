"""Abstract base parser interface."""

from abc import ABC, abstractmethod
from ..models.common import ParserEnvelope, ParseResult


class BaseParser(ABC):
    """Base interface for all source-specific data decoders."""

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Name of the parser destination (e.g. SAIS, MSIS, LRIT, etc.)."""
        pass

    @abstractmethod
    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        """Parse incoming envelope into structured CommonVesselRecords."""
        pass
