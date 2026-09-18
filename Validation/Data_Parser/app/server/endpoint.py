"""TCP NDJSON Endpoint Listener for Data Parser service."""

import json
import logging
import socket
import threading
from typing import Dict, List, Optional

from ..metrics.collector import ParserMetricsCollector
from ..models.common import ParserEnvelope, ParseResult
from ..parsers.base import BaseParser
from ..pipeline.processor import PipelineProcessor


class ParserEndpointServer:
    """Listens on a designated TCP port and processes routed envelopes."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        parser: BaseParser,
        metrics_collector: ParserMetricsCollector,
        framing: str = "ndjson",
        logger: Optional[logging.Logger] = None,
        processor: Optional[PipelineProcessor] = None,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.parser = parser
        self.metrics_collector = metrics_collector
        self.framing = framing
        self.logger = logger or logging.getLogger("parser")
        self.processor = processor or PipelineProcessor()

        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Bind and begin listening on the TCP port."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(128)
        self._server_sock.settimeout(1.0)
        self._running = True

        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name=f"Parser-{self.name}")
        self._thread.start()
        self.logger.info(f"Parser endpoint '{self.name}' listening on {self.host}:{self.port}")

    def stop(self):
        """Shut down the endpoint listener."""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.logger.info(f"Parser endpoint '{self.name}' stopped.")

    def _listen_loop(self):
        while self._running:
            try:
                client_sock, client_addr = self._server_sock.accept()
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client_sock, client_addr), daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self._running:
                    self.logger.error(f"Error accepting connection on {self.name}: {e}")

    def _handle_client(self, client_sock: socket.socket, client_addr):
        client_sock.settimeout(10.0)
        buffer = b""
        try:
            while self._running:
                chunk = client_sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    ack_payload = self._process_envelope_line(line)
                    ack_bytes = json.dumps(ack_payload).encode("utf-8") + b"\n"
                    client_sock.sendall(ack_bytes)

        except (ConnectionResetError, BrokenPipeError, socket.timeout):
            pass
        except Exception as e:
            self.logger.error(f"Error handling client {client_addr} on {self.name}: {e}")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _process_envelope_line(self, line: bytes) -> dict:
        try:
            data = json.loads(line.decode("utf-8"))
            envelope = ParserEnvelope.from_dict(data)
        except Exception as e:
            self.logger.error(f"Failed to deserialize envelope on {self.name}: {e}")
            return {
                "status": "NACK",
                "message_id": "unknown",
                "parser": self.name,
                "error": f"Invalid envelope JSON: {str(e)}",
            }

        # Parse using pipeline processor
        try:
            result, generated_xml = self.processor.process_envelope(
                envelope=envelope,
                fallback_source_parser=self.parser,
            )
            self.metrics_collector.record_parse_result(
                source=envelope.source,
                records_parsed=result.records_parsed,
                records_rejected=result.records_rejected,
                errors=result.errors,
            )
            return result.to_ack_dict(self.name)
        except Exception as e:
            self.logger.error(f"Unhandled error in parser {self.name} for {envelope.message_id}: {e}")
            return {
                "status": "NACK",
                "message_id": envelope.message_id,
                "parser": self.name,
                "source": envelope.source,
                "error": f"Parser execution failure: {str(e)}",
            }
