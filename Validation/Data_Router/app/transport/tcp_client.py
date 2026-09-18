"""Low-level TCP client for sending envelopes to Data Parsers and awaiting ACKs."""

import socket
import struct
import threading
import time
from typing import Optional, Tuple

from ..queue.item import QueueItem
from ..reliability.acknowledgement import AckResult, validate_ack_response


class TransportError(Exception):
    """Raised on socket transport errors."""
    pass


class ParserTCPClient:
    """Manages a single connection to a Data Parser endpoint."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        framing: str = "ndjson",
        timeout: float = 5.0,
        keep_alive: bool = True,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.framing = framing.lower()
        self.timeout = timeout
        self.keep_alive = keep_alive
        
        self._sock: Optional[socket.socket] = None
        self._lock = threading.RLock()
        self._last_connected_at: Optional[float] = None
        self._last_delivery_at: Optional[float] = None

    def is_connected(self) -> bool:
        """Check if socket is currently established."""
        return self._sock is not None

    def connect(self) -> None:
        """Establish TCP connection to the parser endpoint."""
        with self._lock:
            if self._sock is not None:
                return

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                if self.keep_alive:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

                sock.connect((self.host, self.port))
                self._sock = sock
                self._last_connected_at = time.time()
            except (socket.error, OSError) as e:
                try:
                    sock.close()
                except Exception:
                    pass
                self._sock = None
                raise TransportError(f"Failed to connect to parser '{self.name}' at {self.host}:{self.port} - {e}") from e

    def disconnect(self) -> None:
        """Close current connection safely."""
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def deliver_and_await_ack(self, item: QueueItem) -> AckResult:
        """Send queue item envelope to parser and await ACK response."""
        with self._lock:
            try:
                if self._sock is None:
                    self.connect()

                wire_data = item.envelope.to_wire_bytes(self.framing)

                assert self._sock is not None
                self._sock.settimeout(self.timeout)
                self._sock.sendall(wire_data)

                # Receive ACK response according to framing
                raw_ack = self._read_response(self._sock)
                result = validate_ack_response(raw_ack, item.message_id)

                if result.success:
                    self._last_delivery_at = time.time()

                return result

            except (socket.timeout, TimeoutError) as e:
                self.disconnect()
                return AckResult(
                    success=False,
                    message_id=item.message_id,
                    status="TIMEOUT",
                    error=f"Timeout awaiting ACK from parser '{self.name}' ({self.timeout}s): {e}"
                )
            except (socket.error, OSError, TransportError) as e:
                self.disconnect()
                return AckResult(
                    success=False,
                    message_id=item.message_id,
                    status="CONNECTION_ERROR",
                    error=f"Socket error with parser '{self.name}': {e}"
                )

    def _read_response(self, sock: socket.socket) -> str:
        """Read a single framed response from parser socket."""
        if self.framing == "length_prefixed":
            # Read 4-byte big-endian length
            length_bytes = self._read_exact(sock, 4)
            payload_len = struct.unpack(">I", length_bytes)[0]
            payload_bytes = self._read_exact(sock, payload_len)
            return payload_bytes.decode("utf-8")
        else:
            # Newline-delimited line reading
            buffer = bytearray()
            while True:
                chunk = sock.recv(1)
                if not chunk:
                    raise TransportError("Connection closed by downstream parser while waiting for response")
                if chunk == b"\n":
                    break
                buffer.extend(chunk)
                if len(buffer) > 65536:
                    raise TransportError("Parser ACK response exceeded maximum size limit (64KB)")
            return buffer.decode("utf-8").strip()

    def _read_exact(self, sock: socket.socket, num_bytes: int) -> bytes:
        """Read exact number of bytes from socket."""
        buffer = bytearray()
        while len(buffer) < num_bytes:
            packet = sock.recv(num_bytes - len(buffer))
            if not packet:
                raise TransportError("Connection closed unexpectedly while reading bytes")
            buffer.extend(packet)
        return bytes(buffer)
