"""TCP NDJSON Endpoint Listener for Data Parser service."""

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Dict, List, Optional

from ..metrics.collector import ParserMetricsCollector
from ..models.common import ParserEnvelope, ParseResult
from ..parsers.base import BaseParser
from ..pipeline.processor import PipelineProcessor
from .ingress_queue import DurableIngressQueue


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

        ingress_root = Path(
            os.environ.get(
                "VALIDATION_PARSER_INGRESS_DIR",
                str(Path.cwd() / "Validation" / "state" / "parser-ingress"),
            )
        )
        self.ingress_queue = DurableIngressQueue(
            root_dir=ingress_root,
            endpoint_name=name,
            processor=self.processor,
            parser=self.parser,
            metrics_collector=self.metrics_collector,
            logger=self.logger,
        )

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
        self.ingress_queue.start()
        self.logger.info(f"Parser endpoint '{self.name}' listening on {self.host}:{self.port}")

    def stop(self):
        """Shut down the endpoint listener."""
        self._running = False
        self.ingress_queue.stop()
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

        # ACK is returned after the complete envelope has been atomically
        # persisted to the durable parser ingress queue. The parse/normalize/
        # enrich/XML work runs in the background worker. This prevents large
        # MSIS/LRIT/SAIS files from exceeding the Router ACK timeout and
        # prevents a timeout from causing duplicate processing.
        try:
            accepted = self.ingress_queue.enqueue(envelope)
            if not accepted:
                return {
                    "status": "NACK",
                    "message_id": envelope.message_id,
                    "parser": self.name,
                    "source": envelope.source,
                    "error": "Parser durable ingress queue rejected the envelope",
                }
            return {
                "status": "ACK",
                "message_id": envelope.message_id,
                "parser": self.name,
                "source": envelope.source,
                "accepted": True,
            }
        except Exception as e:
            self.logger.exception(
                f"Unhandled parser ingress error on {self.name} for {envelope.message_id}: {e}"
            )
            return {
                "status": "NACK",
                "message_id": envelope.message_id,
                "parser": self.name,
                "source": envelope.source,
                "error": f"Parser ingress failure: {str(e)}",
            }
