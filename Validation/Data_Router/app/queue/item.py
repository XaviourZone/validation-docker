"""Ingestion envelope and queue item data models."""

import json
import struct
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RoutingEnvelope:
    """Standardized metadata envelope carrying routed maritime data."""
    message_id: str
    source: str
    input_type: str  # "FILE" or "TCP"
    received_at: str
    payload: str
    filename: Optional[str] = None
    file_size: Optional[int] = None
    file_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to dictionary excluding None values for optional fields."""
        data = {
            "message_id": self.message_id,
            "source": self.source,
            "input_type": self.input_type,
            "received_at": self.received_at,
            "payload": self.payload,
        }
        if self.filename is not None:
            data["filename"] = self.filename
        if self.file_size is not None:
            data["file_size"] = self.file_size
        if self.file_hash is not None:
            data["file_hash"] = self.file_hash
        return data

    def to_json(self) -> str:
        """Serialize envelope to single-line JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_wire_bytes(self, framing: str = "ndjson") -> bytes:
        """Encode envelope into wire format based on framing strategy."""
        json_str = self.to_json()
        raw_bytes = json_str.encode("utf-8")

        if framing.lower() == "length_prefixed":
            # 4-byte big-endian prefix + payload bytes
            prefix = struct.pack(">I", len(raw_bytes))
            return prefix + raw_bytes
        else:
            # Default: Newline-Delimited JSON (NDJSON)
            return raw_bytes + b"\n"


@dataclass
class QueueItem:
    """Encapsulates an envelope within internal router queues."""
    envelope: RoutingEnvelope
    parser_destination: str
    destination_host: str
    destination_port: int
    attempt_count: int = 0
    next_attempt_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def message_id(self) -> str:
        return self.envelope.message_id

    @property
    def source(self) -> str:
        return self.envelope.source

    def is_eligible_for_attempt(self, current_time: Optional[float] = None) -> bool:
        """Check if backoff delay has elapsed."""
        now = current_time if current_time is not None else time.time()
        return now >= self.next_attempt_at
