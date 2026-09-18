"""Destination endpoint definition for Data Parsers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParserDestination:
    """Represents a target downstream parser service."""
    name: str
    host: str
    port: int
    framing: str = "ndjson"

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"
