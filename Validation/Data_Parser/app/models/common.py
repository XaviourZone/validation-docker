"""Common data models and internal vessel representation for Data Parser."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ParserEnvelope:
    """Incoming envelope forwarded by Data Router over TCP."""
    message_id: str
    source: str
    input_type: str
    received_at: str
    payload: str
    filename: Optional[str] = None
    file_size: Optional[int] = None
    file_hash: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParserEnvelope":
        return cls(
            message_id=data["message_id"],
            source=data["source"],
            input_type=data.get("input_type", "FILE"),
            received_at=data.get("received_at", datetime.now(timezone.utc).isoformat()),
            payload=data.get("payload", ""),
            filename=data.get("filename"),
            file_size=data.get("file_size"),
            file_hash=data.get("file_hash"),
        )


@dataclass
class CommonVesselRecord:
    """Standardized internal vessel position / static record.
    
    Preserves source provenance and normalizes core navigation/identity attributes.
    """
    source: str                          # Original source (e.g. SAIS_IOR, SAIS_GLOBAL, MSIS, etc.)
    message_id: str                      # Router envelope message_id
    record_id: str                       # Unique per-record identifier
    timestamp: str                       # ISO-8601 UTC timestamp
    mmsi: Optional[int] = None           # 9-digit Maritime Mobile Service Identity
    imo: Optional[int] = None            # International Maritime Organization number
    vessel_name: Optional[str] = None    # Cleaned vessel name
    callsign: Optional[str] = None       # Radio call sign
    latitude: Optional[float] = None     # Decimal degrees (-90.0 to 90.0)
    longitude: Optional[float] = None    # Decimal degrees (-180.0 to 180.0)
    sog: Optional[float] = None          # Speed over ground in knots
    cog: Optional[float] = None          # Course over ground in degrees (0.0 to 360.0)
    true_heading: Optional[float] = None # True heading in degrees (0 to 359)
    nav_status: Optional[int] = None     # Navigational status code (0 to 15)
    rot: Optional[float] = None          # Rate of turn
    draught: Optional[float] = None      # Current draught in meters
    vessel_type: Optional[str] = None    # Vessel type description or code
    destination: Optional[str] = None    # Stated destination port/area
    eta: Optional[str] = None            # Estimated time of arrival
    length: Optional[float] = None       # Overall length in meters
    width: Optional[float] = None        # Overall beam/width in meters
    app_message_id: Optional[int] = None # Decoded AIS message type (1, 2, 3, 5, etc.)
    raw_payload: Optional[str] = None    # Original raw sentence or line for auditability

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ParseResult:
    """Result of parsing an entire incoming envelope."""
    message_id: str
    source: str
    success: bool
    records_parsed: int
    records_rejected: int
    records: List[CommonVesselRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_ack_dict(self, parser_name: str) -> Dict[str, Any]:
        """Generate standard ACK/NACK response dictionary for Data Router."""
        return {
            "status": "ACK" if self.success else "NACK",
            "message_id": self.message_id,
            "parser": parser_name,
            "source": self.source,
            "records_parsed": self.records_parsed,
            "records_rejected": self.records_rejected,
            "error_count": len(self.errors),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
