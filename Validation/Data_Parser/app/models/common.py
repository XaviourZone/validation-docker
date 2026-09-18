"""Common data models for Router -> Parser -> Enrichment -> XML."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ParserEnvelope:
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
    """One logical source transmission/line after source-specific decoding."""
    source: str
    message_id: str
    record_id: str
    timestamp: str
    mmsi: Optional[int] = None
    imo: Optional[int] = None
    vessel_name: Optional[str] = None
    callsign: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    sog: Optional[float] = None
    cog: Optional[float] = None
    true_heading: Optional[float] = None
    nav_status: Optional[int] = None
    rot: Optional[float] = None
    draught: Optional[float] = None
    vessel_type: Optional[str] = None
    destination: Optional[str] = None
    eta: Optional[str] = None
    length: Optional[float] = None
    width: Optional[float] = None
    len_to_bow: Optional[float] = None
    len_to_stern: Optional[float] = None
    width_to_port: Optional[float] = None
    width_to_starboard: Optional[float] = None
    gross_tonnage: Optional[float] = None
    altitude: Optional[float] = None
    origin: Optional[str] = None
    arrival: Optional[str] = None
    departure: Optional[str] = None
    app_message_id: Optional[int] = None
    raw_payload: Optional[str] = None
    raw_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ParseResult:
    message_id: str
    source: str
    success: bool
    records_parsed: int
    records_rejected: int
    records: List[CommonVesselRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_ack_dict(self, parser_name: str) -> Dict[str, Any]:
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
