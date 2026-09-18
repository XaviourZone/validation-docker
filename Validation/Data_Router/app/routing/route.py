"""Route mapping associating an input source with a parser destination."""

from dataclasses import dataclass
from .destination import ParserDestination


@dataclass(frozen=True)
class Route:
    """A configured routing path from source to parser destination."""
    source_name: str
    destination: ParserDestination
