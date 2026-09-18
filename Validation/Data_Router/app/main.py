"""Master service lifecycle coordinator and CLI entrypoint for Validation Data Router."""

import argparse
import logging
import os
from pathlib import Path
import signal
import sys
import time
from typing import Dict, List, Optional

from . import __version__
from .config.loader import ConfigurationError, load_config, validate_config
from .config.models import FileSourceConfig, RouterConfig, TCPSourceConfig
from .logging.logger import log_event, setup_logging
from .monitoring.health import HealthEvaluator, MonitoringServer
from .monitoring.metrics import MetricsCollector
from .queue.manager import BoundedQueueManager
from .reliability.state import FileStateStore
from .routing.router import RoutingEngine
from .sources.base_source import BaseSource
from .sources.file_source import FileSourceManager
from .sources.tcp_source import TCPSourceManager
from .transport.connection_manager import ParserConnectionManager


class DataRouterService:
    """Production daemon coordinating sources, queues, routing, and monitoring."""

    def __init__(self, config_path: str, base_dir: Optional[Path] = None):
        self.config_path = Path(config_path)
        self.base_dir = base_dir or self.config_path.parent.parent

        # 1. Setup logging
        logging_yaml = self.base_dir / "config" / "logging.yaml"
        self.logger = setup_logging(
            config_path=str(logging_yaml) if logging_yaml.exists() else None,
            base_dir=self.base_dir
        )

        self.logger.info(f"Initializing Validation Data Router Service v{__version__}...")

        # 2. Load and validate configuration
        self.config: RouterConfig = load_config(self.config_path)

        # 3. Initialize SQLite state store
        db_path = Path(self.config.state.db_path)
        if not db_path.is_absolute():
            db_path = self.base_dir / db_path
        self.state_store = FileStateStore(db_path=db_path)
        self.logger.info(f"State store initialized at {db_path.resolve()}")

        # 4. Initialize metrics and queue
        self.metrics = MetricsCollector()
        self.queue_manager = BoundedQueueManager(self.config.queue)

        # 5. Initialize transport & routing engine
        self.connection_manager = ParserConnectionManager(
            destinations=self.config.parser_destinations,
            logger=self.logger,
        )
        self.routing_engine = RoutingEngine(
            config=self.config,
            queue_manager=self.queue_manager,
            connection_manager=self.connection_manager,
            state_store=self.state_store,
            metrics_collector=self.metrics,
            logger=self.logger,
        )

        # 6. Initialize health evaluator & monitoring server
        self.evaluator = HealthEvaluator(
            queue_manager=self.queue_manager,
            connection_manager=self.connection_manager,
            metrics_collector=self.metrics,
        )
        self.monitoring_server = MonitoringServer(
            config=self.config.monitoring,
            evaluator=self.evaluator,
            logger=self.logger,
        )

        # 7. Initialize source managers
        self.sources: Dict[str, BaseSource] = {}
        self._init_sources()

        self._running = False

    def _init_sources(self) -> None:
        """Instantiate source managers according to configuration."""
        inflow_dir = Path(self.config.data_inflow.base_dir)
        if not inflow_dir.is_absolute():
            # Support either workspace root or base_dir
            candidate_workspace = self.base_dir.parent.parent / inflow_dir
            if candidate_workspace.exists():
                inflow_dir = candidate_workspace
            else:
                inflow_dir = self.base_dir / inflow_dir

        for src_name, src_cfg in self.config.sources.items():
            self.metrics.register_source(src_name, enabled=src_cfg.enabled)

            if isinstance(src_cfg, FileSourceConfig):
                source_inst = FileSourceManager(
                    config=src_cfg,
                    base_inflow_dir=inflow_dir,
                    routing_engine=self.routing_engine,
                    state_store=self.state_store,
                    metrics_collector=self.metrics,
                    logger=self.logger,
                )
                self.sources[src_name] = source_inst

            elif isinstance(src_cfg, TCPSourceConfig):
                source_inst = TCPSourceManager(
                    config=src_cfg,
                    routing_engine=self.routing_engine,
                    metrics_collector=self.metrics,
                    logger=self.logger,
                )
                self.sources[src_name] = source_inst

    def start(self) -> None:
        """Start all background workers, monitoring, and source inputs."""
        self.logger.info("Starting Data Router subsystems...")
        self._running = True

        # Check recovery state
        incomplete = self.state_store.get_incomplete_records()
        if incomplete:
            self.logger.info(f"Found {len(incomplete)} interrupted records from prior run; will be re-evaluated.")

        # Start routing engine (delivery workers)
        self.routing_engine.start()

        # Start HTTP monitoring
        self.monitoring_server.start()

        # Start source pollers / receivers
        for src_name, source in self.sources.items():
            if source.config.enabled:
                source.start()

        self.logger.info("Data Router Service is fully OPERATIONAL.")

    def stop(self) -> None:
        """Gracefully shut down all components."""
        if not self._running:
            return

        self.logger.info("Initiating graceful shutdown of Data Router Service...")
        self._running = False

        # 1. Stop sources from ingesting new data
        for src_name, source in self.sources.items():
            try:
                source.stop()
            except Exception as e:
                self.logger.warning(f"Error stopping source '{src_name}': {e}")

        # 2. Stop routing engine and drain workers
        self.routing_engine.stop(drain_timeout=5.0)

        # 3. Stop monitoring server
        self.monitoring_server.stop()

        self.logger.info("Data Router Service shutdown COMPLETE.")

    def run_forever(self) -> None:
        """Block main thread and handle termination signals."""
        def handle_signal(sig, frame):
            sig_name = signal.Signals(sig).name
            self.logger.info(f"Received signal {sig_name}, shutting down...")
            self.stop()
            sys.exit(0)

        # Register signals (SIGINT and SIGTERM)
        signal.signal(signal.SIGINT, handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handle_signal)

        self.start()

        while self._running:
            try:
                time.sleep(1.0)
            except KeyboardInterrupt:
                self.stop()
                break


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="validation-router",
        description="Validation Data Router Service — Maritime data ingestion & routing daemon."
    )
    parser.add_argument(
        "--config", "-c",
        default="Validation/Data_Router/config/sources.yaml",
        help="Path to sources.yaml configuration file."
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration file syntax and semantics, then exit."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Query and print health status from local monitoring endpoint, then exit."
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    args = parser.parse_args()

    # Determine config file path
    config_file = Path(args.config)
    if not config_file.exists():
        # Try finding relative to script or cwd
        candidates = [
            Path("Validation/Data_Router/config/sources.yaml"),
            Path("config/sources.yaml"),
            Path(__file__).parent.parent / "config" / "sources.yaml",
        ]
        for c in candidates:
            if c.exists():
                config_file = c
                break

    if args.validate_config:
        try:
            print(f"Validating configuration at: {config_file.resolve()} ...")
            cfg = load_config(config_file)
            print("OK: Configuration is VALID.")
            print(f"  Destinations: {list(cfg.parser_destinations.keys())}")
            print(f"  Sources: {list(cfg.sources.keys())}")
            sys.exit(0)
        except Exception as e:
            print(f"ERROR: Configuration is INVALID:\n{e}", file=sys.stderr)
            sys.exit(1)

    if args.status:
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/status", timeout=3.0) as resp:
                print(resp.read().decode("utf-8"))
                sys.exit(0)
        except Exception as e:
            print(f"ERROR: Could not connect to Data Router monitoring endpoint: {e}", file=sys.stderr)
            sys.exit(1)

    # Launch daemon
    try:
        service = DataRouterService(config_path=str(config_file))
        service.run_forever()
    except Exception as e:
        print(f"FATAL: Service encountered unrecoverable error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
