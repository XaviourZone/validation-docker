"""TCP stream input manager with configurable message framing and automatic reconnection."""

import logging
import socket
import struct
import threading
import time
from typing import Optional

from .base_source import BaseSource
from ..config.models import FramingType, TCPSourceConfig
from ..logging.logger import log_event
from ..monitoring.metrics import MetricsCollector
from ..queue.item import RoutingEnvelope
from ..reliability.retry import calculate_backoff_delay
from ..routing.router import RoutingEngine
from ..utils.hashing import generate_tcp_message_id
from ..utils.time import now_iso


class TCPSourceManager(BaseSource):
    """Maintains a persistent TCP client connection to a remote stream, framing messages into envelopes."""

    def __init__(
        self,
        config: TCPSourceConfig,
        routing_engine: RoutingEngine,
        metrics_collector: Optional[MetricsCollector] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(config, logger)
        self.tcp_config = config
        self.routing_engine = routing_engine
        self.metrics_collector = metrics_collector

        self._running = False
        self._connected = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def is_running(self) -> bool:
        return self._running

    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Start the TCP feed receiver worker thread."""
        if not self.config.enabled:
            self.logger.info(f"TCP source '{self.name}' is disabled in configuration.")
            return

        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._connection_loop,
            name=f"TCPReceiver-{self.name}",
            daemon=True,
        )
        self._thread.start()
        if self.metrics_collector:
            self.metrics_collector.set_source_state(self.name, running=True, connected=False)

        self.logger.info(
            f"TCP source '{self.name}' started connecting to {self.tcp_config.remote_host}:{self.tcp_config.remote_port}"
        )

    def stop(self) -> None:
        """Stop receiver thread and close connection."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        # Close socket to interrupt blocking recv()
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

        self._connected = False
        if self.metrics_collector:
            self.metrics_collector.set_source_state(self.name, running=False, connected=False)

        self.logger.info(f"TCP source '{self.name}' stopped")

    def _connection_loop(self) -> None:
        """Outer loop maintaining connection with exponential backoff on drop."""
        reconnect_attempts = 0
        host = self.tcp_config.remote_host
        port = self.tcp_config.remote_port

        while not self._stop_event.is_set():
            try:
                self._connect_and_stream(host, port)
                reconnect_attempts = 0  # Reset after successful run
            except (socket.error, OSError) as e:
                self._connected = False
                if self.metrics_collector:
                    self.metrics_collector.set_source_state(self.name, connected=False)

                if self._stop_event.is_set():
                    break

                reconnect_attempts += 1
                delay = calculate_backoff_delay(
                    attempt=reconnect_attempts,
                    initial_delay=self.tcp_config.reconnect_initial_delay,
                    max_delay=self.tcp_config.reconnect_max_delay,
                    multiplier=self.tcp_config.reconnect_multiplier,
                )

                log_event(
                    self.logger,
                    logging.WARNING,
                    event="connection_lost",
                    source=self.name,
                    destination=f"{host}:{port}",
                    reconnect_in_seconds=round(delay, 2),
                    attempt=reconnect_attempts,
                    error=str(e),
                )
                if self.metrics_collector:
                    self.metrics_collector.record_error(self.name, str(e))

                self._stop_event.wait(timeout=delay)

    def _connect_and_stream(self, host: str, port: int) -> None:
        """Establish connection and stream framed messages."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(10.0)

        log_event(
            self.logger,
            logging.INFO,
            event="connecting",
            source=self.name,
            destination=f"{host}:{port}",
        )

        try:
            sock.connect((host, port))
            self._sock = sock
            self._connected = True

            log_event(
                self.logger,
                logging.INFO,
                event="connected",
                source=self.name,
                destination=f"{host}:{port}",
            )
            if self.metrics_collector:
                self.metrics_collector.set_source_state(self.name, connected=True)

            sock.settimeout(0.5)
            self._stream_messages(sock)
        finally:
            self._connected = False
            self._sock = None
            try:
                sock.close()
            except Exception:
                pass

    def _stream_messages(self, sock: socket.socket) -> None:
        """Read stream and frame messages based on configuration."""
        framing = self.tcp_config.framing

        if framing == FramingType.LINE:
            self._stream_line_delimited(sock)
        elif framing == FramingType.LENGTH_PREFIXED:
            self._stream_length_prefixed(sock)
        else:
            # Fallback for unconfigured feeds: PENDING INPUT SPECIFICATION
            self.logger.warning(
                f"Source '{self.name}' framing '{framing}' is PENDING INPUT SPECIFICATION. Falling back to line framing."
            )
            self._stream_line_delimited(sock)

    def _stream_line_delimited(self, sock: socket.socket) -> None:
        """Read newline/delimiter delimited stream."""
        delimiter = self.tcp_config.delimiter.encode("utf-8")
        max_len = self.tcp_config.max_line_length
        buffer = bytearray()

        while not self._stop_event.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise socket.error("Remote feed closed connection")

            buffer.extend(chunk)

            while delimiter in buffer:
                idx = buffer.index(delimiter)
                line_bytes = buffer[:idx]
                buffer = buffer[idx + len(delimiter):]

                # Strip possible trailing \r
                if line_bytes.endswith(b"\r"):
                    line_bytes = line_bytes[:-1]

                if line_bytes:
                    message_str = line_bytes.decode("utf-8", errors="replace").strip()
                    if message_str:
                        self._route_message(message_str)

            if len(buffer) > max_len:
                self.logger.warning(f"Line buffer for source '{self.name}' exceeded {max_len} bytes; dropping buffer.")
                buffer.clear()

    def _stream_length_prefixed(self, sock: socket.socket) -> None:
        """Read 4-byte length prefixed frames."""
        while not self._stop_event.is_set():
            # Read 4-byte header
            header = self._recv_exact(sock, 4)
            payload_len = struct.unpack(">I", header)[0]
            if payload_len > self.tcp_config.max_line_length:
                raise socket.error(f"Length prefix {payload_len} exceeded maximum limit")

            payload_bytes = self._recv_exact(sock, payload_len)
            message_str = payload_bytes.decode("utf-8", errors="replace")
            self._route_message(message_str)

    def _recv_exact(self, sock: socket.socket, n_bytes: int) -> bytes:
        """Read exactly n_bytes from socket."""
        buf = bytearray()
        while len(buf) < n_bytes:
            packet = sock.recv(n_bytes - len(buf))
            if not packet:
                raise socket.error("Connection closed while reading framed packet")
            buf.extend(packet)
        return bytes(buf)

    def _route_message(self, payload: str) -> None:
        """Wrap received stream message in envelope and route."""
        msg_id = generate_tcp_message_id(self.name)
        envelope = RoutingEnvelope(
            message_id=msg_id,
            source=self.name,
            input_type="TCP",
            received_at=now_iso(),
            payload=payload,
        )

        if self.metrics_collector:
            self.metrics_collector.record_received(self.name)

        self.routing_engine.route(envelope)
