"""Routing engine delivering enveloped items to destination parsers with retry and state tracking."""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .destination import ParserDestination
from .route import Route
from ..config.models import RouterConfig
from ..logging.logger import log_event
from ..queue.item import QueueItem, RoutingEnvelope
from ..queue.manager import BoundedQueueManager
from ..reliability.retry import RetryPolicy
from ..reliability.state import FileState, FileStateStore
from ..transport.connection_manager import ParserConnectionManager


class RoutingEngine:
    """Core routing engine managing destination resolution, queues, and delivery workers."""

    def __init__(
        self,
        config: RouterConfig,
        queue_manager: BoundedQueueManager,
        connection_manager: ParserConnectionManager,
        state_store: Optional[FileStateStore] = None,
        metrics_collector: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config
        self.queue_manager = queue_manager
        self.connection_manager = connection_manager
        self.state_store = state_store
        self.metrics_collector = metrics_collector
        self.logger = logger or logging.getLogger("router")
        self.retry_policy = RetryPolicy(config.retry)

        self._routes: Dict[str, Route] = {}
        self._init_routes()

        self._workers: List[threading.Thread] = []
        self._running = False
        self._stop_event = threading.Event()

    def _init_routes(self) -> None:
        """Construct routing table from configuration."""
        for src_name, src_cfg in self.config.sources.items():
            parser_name = src_cfg.parser
            dest_cfg = self.config.parser_destinations.get(parser_name)
            if dest_cfg:
                dest = ParserDestination(
                    name=dest_cfg.name,
                    host=dest_cfg.host,
                    port=dest_cfg.port,
                    framing=dest_cfg.framing,
                )
                self._routes[src_name] = Route(source_name=src_name, destination=dest)

    def get_route(self, source_name: str) -> Optional[Route]:
        """Look up configured route for source."""
        return self._routes.get(source_name)

    def route(self, envelope: RoutingEnvelope, timeout: float = 5.0) -> bool:
        """Wrap and enqueue an incoming data envelope for delivery."""
        route = self.get_route(envelope.source)
        if not route:
            log_event(
                self.logger,
                logging.ERROR,
                event="routing_failed",
                source=envelope.source,
                message_id=envelope.message_id,
                error=f"No route found for source '{envelope.source}'",
            )
            return False

        item = QueueItem(
            envelope=envelope,
            parser_destination=route.destination.name,
            destination_host=route.destination.host,
            destination_port=route.destination.port,
        )

        accepted = self.queue_manager.put(item, timeout=timeout)
        if accepted:
            if self.state_store and envelope.input_type == "FILE":
                self.state_store.update_status(
                    message_id=envelope.message_id,
                    status=FileState.QUEUED,
                    destination=route.destination.address,
                )

            if self.metrics_collector:
                self.metrics_collector.record_routed(envelope.source)

            log_event(
                self.logger,
                logging.INFO,
                event="queued",
                source=envelope.source,
                filename=envelope.filename,
                message_id=envelope.message_id,
                destination=route.destination.address,
            )
            return True
        else:
            log_event(
                self.logger,
                logging.WARNING,
                event="queue_rejected",
                source=envelope.source,
                filename=envelope.filename,
                message_id=envelope.message_id,
                error="Queue is full or congested",
            )
            return False

    def start(self) -> None:
        """Start delivery worker threads."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Resume interrupted files across crashes/restarts
        if self.state_store:
            reset_count = self.state_store.reset_interrupted_states()
            if reset_count > 0:
                self.logger.info(f"Reset {reset_count} interrupted file states to DISCOVERED for recovery")

        worker_count = self.config.queue.worker_count

        for i in range(worker_count):
            t = threading.Thread(
                target=self._delivery_worker_loop,
                name=f"DeliveryWorker-{i+1}",
                daemon=True,
            )
            self._workers.append(t)
            t.start()

        self.logger.info(f"RoutingEngine started with {worker_count} delivery workers")

    def stop(self, drain_timeout: float = 5.0) -> None:
        """Gracefully stop routing engine and workers."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        self.queue_manager.stop()

        # Wait for workers to exit
        deadline = time.time() + drain_timeout
        for t in self._workers:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)

        self._workers.clear()
        self.connection_manager.disconnect_all()
        self.logger.info("RoutingEngine stopped gracefully")

    def _delivery_worker_loop(self) -> None:
        """Worker thread loop consuming queue and dispatching to parsers."""
        while not self._stop_event.is_set():
            item = self.queue_manager.get(timeout=1.0)
            if item is None:
                continue

            try:
                self._process_delivery(item)
            except Exception as e:
                self.logger.exception(f"Unexpected error in delivery worker: {e}")
            finally:
                self.queue_manager.task_done()

    def _process_delivery(self, item: QueueItem) -> None:
        """Execute a delivery attempt with ACK validation and retry handling."""
        source = item.envelope.source
        filename = item.envelope.filename
        msg_id = item.envelope.message_id
        dest_addr = f"{item.destination_host}:{item.destination_port}"

        if self.state_store and item.envelope.input_type == "FILE":
            self.state_store.update_status(msg_id, FileState.SENDING)

        log_event(
            self.logger,
            logging.DEBUG,
            event="sending",
            source=source,
            filename=filename,
            message_id=msg_id,
            destination=dest_addr,
            attempt=item.attempt_count + 1,
        )

        ack_result = self.connection_manager.deliver(item)

        if ack_result.success:
            if self.state_store and item.envelope.input_type == "FILE":
                self.state_store.update_status(msg_id, FileState.ACKNOWLEDGED)
                self.state_store.update_status(msg_id, FileState.PROCESSED)

            if self.metrics_collector:
                self.metrics_collector.record_acknowledged(source)

            log_event(
                self.logger,
                logging.INFO,
                event="acknowledged",
                source=source,
                filename=filename,
                message_id=msg_id,
                destination=dest_addr,
            )

        else:
            item.attempt_count += 1
            if self.state_store and item.envelope.input_type == "FILE":
                self.state_store.increment_attempt(msg_id, error=ack_result.error)

            if self.retry_policy.can_retry(item.attempt_count):
                delay = self.retry_policy.get_delay(item.attempt_count)
                if self.state_store and item.envelope.input_type == "FILE":
                    self.state_store.update_status(msg_id, FileState.RETRYING, error=ack_result.error)

                if self.metrics_collector:
                    self.metrics_collector.record_retry(source)

                log_event(
                    self.logger,
                    logging.WARNING,
                    event="delivery_failed_retrying",
                    source=source,
                    filename=filename,
                    message_id=msg_id,
                    destination=dest_addr,
                    attempt=item.attempt_count,
                    delay_seconds=round(delay, 2),
                    error=ack_result.error,
                )
                self.queue_manager.requeue_for_retry(item, delay)

            else:
                if self.state_store and item.envelope.input_type == "FILE":
                    self.state_store.update_status(msg_id, FileState.FAILED, error=ack_result.error)

                if self.metrics_collector:
                    self.metrics_collector.record_failed(source)

                log_event(
                    self.logger,
                    logging.ERROR,
                    event="delivery_exhausted_failed",
                    source=source,
                    filename=filename,
                    message_id=msg_id,
                    destination=dest_addr,
                    attempts=item.attempt_count,
                    error=ack_result.error,
                )
