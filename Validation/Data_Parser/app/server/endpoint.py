"""TCP NDJSON endpoint for high-throughput asynchronous parser ingress."""

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Optional

from ..metrics.collector import ParserMetricsCollector
from ..models.common import ParserEnvelope
from ..parsers.base import BaseParser
from ..pipeline.processor import PipelineProcessor
from .ingress_queue import DurableIngressQueue


class ParserEndpointServer:
    """Accepts envelopes from Router and never waits for parse completion."""

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
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(128)
        self._server_sock.settimeout(1.0)
        self._running = True

        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name=f"Parser-{self.name}",
        )
        self._thread.start()
        self.ingress_queue.start()
        self.logger.info(
            "Parser endpoint '%s' listening on %s:%s (no application ACK)",
            self.name,
            self.host,
            self.port,
        )

    def stop(self):
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
        self.logger.info("Parser endpoint '%s' stopped.", self.name)

    def _listen_loop(self):
        while self._running:
            try:
                client_sock, client_addr = self._server_sock.accept()
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_addr),
                    daemon=True,
                    name=f"ParserClient-{self.name}",
                )
                client_thread.start()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                if self._running:
                    self.logger.error(
                        "Error accepting connection on %s: %s", self.name, exc
                    )

    def _handle_client(self, client_sock: socket.socket, client_addr):
        client_sock.settimeout(10.0)
        buffer = bytearray()
        try:
            while self._running:
                chunk = client_sock.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)

                while b"\n" in buffer:
                    line, remainder = buffer.split(b"\n", 1)
                    buffer = bytearray(remainder)
                    line = line.strip()
                    if not line:
                        continue

                    # Only persist the envelope. Parsing/enrichment/XML happens
                    # on the background worker and never blocks socket receive.
                    self._process_envelope_line(bytes(line))
        except (ConnectionResetError, BrokenPipeError, socket.timeout):
            pass
        except Exception as exc:
            self.logger.error(
                "Error handling parser client %s on %s: %s",
                client_addr,
                self.name,
                exc,
            )
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _process_envelope_line(self, line: bytes) -> bool:
        try:
            data = json.loads(line.decode("utf-8"))
            envelope = ParserEnvelope.from_dict(data)
        except Exception as exc:
            self.logger.error(
                "Dropped invalid envelope on %s: %s", self.name, exc
            )
            return False

        try:
            accepted = self.ingress_queue.enqueue(envelope)
            if not accepted:
                self.logger.error(
                    "Parser ingress persistence failed source=%s file=%s message_id=%s",
                    envelope.source,
                    envelope.filename,
                    envelope.message_id,
                )
                return False
            return True
        except Exception as exc:
            self.logger.exception(
                "Unhandled parser ingress error on %s for %s: %s",
                self.name,
                envelope.message_id,
                exc,
            )
            return False
