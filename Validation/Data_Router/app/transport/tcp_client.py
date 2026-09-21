"""Low-level TCP client for fire-and-forget parser delivery."""

import socket
import struct
import threading
import time
from typing import Optional

from ..queue.item import QueueItem
from ..reliability.acknowledgement import AckResult


class TransportError(Exception):
    """Raised on socket transport errors."""
    pass


class ParserTCPClient:
    """Maintains a reusable TCP connection and never waits for parser ACKs."""

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
        return self._sock is not None

    def connect(self) -> None:
        with self._lock:
            if self._sock is not None:
                return

            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                if self.keep_alive:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.connect((self.host, self.port))
                self._sock = sock
                self._last_connected_at = time.time()
            except (socket.error, OSError) as exc:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self._sock = None
                raise TransportError(
                    f"Failed to connect to parser '{self.name}' "
                    f"at {self.host}:{self.port} - {exc}"
                ) from exc

    def disconnect(self) -> None:
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

    def deliver(self, item: QueueItem) -> AckResult:
        """Send one complete framed envelope and return immediately.

        SUCCESS means the TCP send completed locally. It does not mean that
        parsing, enrichment, XML generation, or Forwarder delivery completed.
        Parser-side durable ingress is responsible for accepting the envelope.
        """
        with self._lock:
            try:
                if self._sock is None:
                    self.connect()

                wire_data = item.envelope.to_wire_bytes(self.framing)
                assert self._sock is not None

                # sendall() waits only for the bytes to be handed to the socket;
                # it does not wait for application-level processing or ACK.
                self._sock.settimeout(self.timeout)
                self._sock.sendall(wire_data)
                self._last_delivery_at = time.time()

                return AckResult(
                    success=True,
                    message_id=item.message_id,
                    status="SENT",
                )
            except (socket.timeout, TimeoutError) as exc:
                self.disconnect()
                return AckResult(
                    success=False,
                    message_id=item.message_id,
                    status="SEND_TIMEOUT",
                    error=f"Timed out sending to parser '{self.name}': {exc}",
                )
            except (socket.error, OSError, TransportError) as exc:
                self.disconnect()
                return AckResult(
                    success=False,
                    message_id=item.message_id,
                    status="SEND_ERROR",
                    error=f"Socket error sending to parser '{self.name}': {exc}",
                )

    # Kept as a compatibility alias for callers/tests that still use the old name.
    def deliver_and_await_ack(self, item: QueueItem) -> AckResult:
        return self.deliver(item)
