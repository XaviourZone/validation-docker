"""CLI and entry point for the Validation Data Parser daemon."""

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import List
import yaml

from .metrics.collector import ParserMetricsCollector
from .parsers.lrit import LRITParser
from .parsers.msis import MSISParser
from .parsers.nais import NAISParser
from .parsers.sais import SAISParser
from .parsers.vatms import VATMSParser
from .parsers.mapped import MappedParser
from .pipeline.mapping_manager import ParserMappingManager
from .pipeline.processor import PipelineProcessor\nfrom .pipeline.reference_db import ReferenceDB
from .server.api_server import ParserAPIServer
from .server.endpoint import ParserEndpointServer


def setup_logger(log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("parser")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [DATA_PARSER] %(message)s"))
        logger.addHandler(handler)
    return logger


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_project_root() -> Path:
    val_home = os.environ.get("VALIDATION_HOME")
    if val_home:
        return Path(val_home).resolve()
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "Validation").exists() or parent.name == "Validation":
            return parent if parent.name != "Validation" else parent.parent
    return Path.cwd()


def main():
    parser = argparse.ArgumentParser(description="Validation Data Parser Service")
    parser.add_argument("--config", type=str, default=None, help="Path to parser.yaml")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    args = parser.parse_args()
    logger = setup_logger(args.log_level)
    workspace_root = resolve_project_root()

    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.is_absolute():
            cfg_path = workspace_root / cfg_path
    else:
        cfg_path = workspace_root / "Validation" / "Data_Parser" / "config" / "parser.yaml"

    try:
        config = load_config(cfg_path)
    except Exception as e:
        logger.error(f"Failed to load config from {cfg_path}: {e}")
        sys.exit(1)

    metrics_collector = ParserMetricsCollector()
    mapping_manager = ParserMappingManager(workspace_root / "Validation" / "Data_Parser" / "config" / "parser_mappings.yaml")
    parser_instances = {
        "SAIS": SAISParser(),
        "MSIS": MSISParser(),
        "LRIT": LRITParser(),
        "VATMS": VATMSParser(),
        "NAIS": NAISParser(),
    }

    # Any endpoint added from the Web Console that does not have a built-in parser
    # uses the mapping-driven generic parser. Built-in AIS/CSV parsers retain their
    # specialized decoders and are not replaced by the generic engine.
    for name in (config.get("endpoints", {}) or {}):
        if name not in parser_instances:
            parser_instances[name] = MappedParser(name, mapping_manager=mapping_manager)

    output_cfg = config.get("output", {}) or {}
    xml_output_dir = output_cfg.get("xml_spool_dir")
    if xml_output_dir:
        xml_output_dir = Path(xml_output_dir)
        if not xml_output_dir.is_absolute():
            xml_output_dir = workspace_root / xml_output_dir
    ref_cfg = config.get("reference_databases", {}) or {}
    def _resolve_ref_path(value):
        if not value:
            return None
        p = Path(value)
        return p if p.is_absolute() else workspace_root / p

    reference_db = ReferenceDB(
        wrs_path=_resolve_ref_path(ref_cfg.get("wrs")),
        pans_path=_resolve_ref_path(ref_cfg.get("pans")),
        nsc_path=_resolve_ref_path(ref_cfg.get("nsc")),
    )

    processor = PipelineProcessor(reference_db=reference_db, xml_output_dir=xml_output_dir)

    endpoints_cfg = config.get("endpoints", {})
    endpoint_servers: List[ParserEndpointServer] = []
    for name, ep_cfg in endpoints_cfg.items():
        port = ep_cfg.get("port")
        host = ep_cfg.get("host", "127.0.0.1")
        framing = ep_cfg.get("framing", "ndjson")
        parser_impl = parser_instances.get(name)
        if not parser_impl:
            logger.warning(f"No parser implementation found for endpoint '{name}', skipping.")
            continue
        server = ParserEndpointServer(name=name, host=host, port=port, parser=parser_impl, metrics_collector=metrics_collector, framing=framing, logger=logger, processor=processor)
        server.start()
        endpoint_servers.append(server)

    srv_cfg = config.get("server", {})
    http_host = srv_cfg.get("http_host", "127.0.0.1")
    http_port = srv_cfg.get("http_port", 8081)
    api_server = ParserAPIServer(host=http_host, port=http_port, metrics_collector=metrics_collector, endpoint_names=list(endpoints_cfg.keys()), logger=logger)
    api_thread = threading.Thread(target=api_server.start, daemon=True, name="Parser-API")
    api_thread.start()

    def shutdown(sig, frame):
        logger.info(f"Signal {sig} received, stopping Data Parser daemon...")
        for s in endpoint_servers:
            s.stop()
        api_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    logger.info("Data Parser service running. Press Ctrl+C to stop.")
    try:
        while True:
            signal.pause() if hasattr(signal, "pause") else threading.Event().wait(1.0)
    except (KeyboardInterrupt, SystemExit):
        for s in endpoint_servers:
            s.stop()
        api_server.shutdown()


if __name__ == "__main__":
    main()
