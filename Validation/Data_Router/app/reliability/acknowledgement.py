"""Parser acknowledgement (ACK) validation protocol."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass(frozen=True)
class AckResult:
    """Result of an ACK evaluation."""
    success: bool
    message_id: str
    status: str
    error: Optional[str] = None


def validate_ack_response(
    raw_response: Union[str, bytes, Dict[str, Any]],
    expected_message_id: str,
) -> AckResult:
    """Parse and validate downstream parser acknowledgement.
    
    Expected schema:
    {
        "message_id": "<str>",
        "status": "ACK" | "NACK",
        "timestamp": "<iso8601>",  (optional)
        "error": "<str>"            (optional)
    }
    """
    if isinstance(raw_response, (str, bytes)):
        try:
            payload: Dict[str, Any] = json.loads(raw_response)
        except Exception as e:
            return AckResult(
                success=False,
                message_id=expected_message_id,
                status="MALFORMED_JSON",
                error=f"Unparseable ACK JSON: {e}"
            )
    elif isinstance(raw_response, dict):
        payload = raw_response
    else:
        return AckResult(
            success=False,
            message_id=expected_message_id,
            status="INVALID_TYPE",
            error=f"Unexpected ACK type: {type(raw_response)}"
        )

    ack_msg_id = payload.get("message_id")
    if not ack_msg_id:
        return AckResult(
            success=False,
            message_id=expected_message_id,
            status="MISSING_MESSAGE_ID",
            error="ACK response is missing 'message_id' field"
        )

    if ack_msg_id != expected_message_id:
        return AckResult(
            success=False,
            message_id=ack_msg_id,
            status="MESSAGE_ID_MISMATCH",
            error=f"ACK message_id '{ack_msg_id}' did not match expected '{expected_message_id}'"
        )

    status_str = str(payload.get("status", "")).upper()
    if status_str != "ACK":
        err_msg = payload.get("error", f"Downstream returned non-ACK status '{status_str}'")
        return AckResult(
            success=False,
            message_id=ack_msg_id,
            status=status_str,
            error=err_msg
        )

    return AckResult(
        success=True,
        message_id=ack_msg_id,
        status="ACK",
        error=None
    )
