"""Connection manager coordinating parser destination client connections."""

import logging
import threading
from typing import Dict, Optional

from .tcp_client import ParserTCPClient
from ..config.models import ParserDestinationConfig
from ..queue.item import QueueItem
from ..reliability.acknowledgement import AckResult


class ParserConnectionManager:
    """Manages reusable TCP clients for all configured parser destinations."""

    def __init__(
        self,
        destinations: Dict[str, ParserDestinationConfig],
        logger: Optional[logging.Logger] = None,
    ):
        self.destinations = destinations
        self.logger = logger or logging.getLogger("router")
        self._clients: Dict[str, ParserTCPClient] = {}
        self._lock = threading.Lock()

        for name, cfg in destinations.items():
            self._clients[name] = ParserTCPClient(
                name=name,
                host=cfg.host,
                port=cfg.port,
                framing=cfg.framing,
                timeout=cfg.timeout_seconds,
                keep_alive=cfg.keep_alive,
            )

    def get_client(self, parser_name: str) -> Optional[ParserTCPClient]:
        with self._lock:
            return self._clients.get(parser_name)

    def deliver(self, item: QueueItem) -> AckResult:
        """Send to the parser socket without waiting for application ACK."""
        client = self.get_client(item.parser_destination)
        if client is None:
            return AckResult(
                success=False,
                message_id=item.message_id,
                status="UNKNOWN_DESTINATION",
                error=f"No parser destination configured for '{item.parser_destination}'",
            )
        return client.deliver(item)

    def get_destination_health(self) -> Dict[str, dict]:
        with self._lock:
            health = {}
            for name, client in self._clients.items():
                health[name] = {
                    "host": client.host,
                    "port": client.port,
                    "connected": client.is_connected(),
                    "last_connected_at": client._last_connected_at,
                    "last_delivery_at": client._last_delivery_at,
                }
            return health

    def disconnect_all(self) -> None:
        with self._lock:
            for name, client in self._clients.items():
                try:
                    client.disconnect()
                except Exception as exc:
                    self.logger.warning(
                        f"Error disconnecting parser client '{name}': {exc}"
                    )
