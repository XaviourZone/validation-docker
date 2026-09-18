"""CLI and entry point for the Validation Web Console daemon."""

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
import yaml

from .config_manager import RouterConfigManager
from .database_client import DatabaseClient
from .database_admin_extension import install_database_admin_extension
from .filesystem_admin_extension import install_filesystem_admin_extension
from .forwarder_client import ForwarderClient
from .forwarder_web import install_forwarder_web_extension
from .router_admin_extension import install_router_admin_extension
from .parser_client import ParserClient
from .router_client import RouterClient
from .server import WebConsoleServer, WebConsoleHandler
from .service_control.factory import get_service_controller
from .system_status import SystemStatusEvaluator


def setup_logger(log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("web_console")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [WEB_CONSOLE] %(message)s"))
        logger.addHandler(handler)
    return logger


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_project_root() -> Path:
    val_home = os.environ.get("VALIDATION_HOME")
    if val_home:
        return Path(val_home).resolve()
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "Validation").exists() or (parent.name == "Validation"):
            return parent if parent.name != "Validation" else parent.parent
    return Path.cwd()


def main():
    parser = argparse.ArgumentParser(description="Validation Maritime Web Console")
    parser.add_argument("--config", type=str, default=None, help="Path to console.yaml")
    parser.add_argument("--host", type=str, default=None, help="Host address to bind")
    parser.add_argument("--port", type=int, default=None, help="Port number to bind")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    args = parser.parse_args()

    logger = setup_logger(args.log_level)
    workspace_root = resolve_project_root()
    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.is_absolute():
            cfg_path = workspace_root / cfg_path
    else:
        cfg_path = workspace_root / "Validation" / "Web_Console" / "config" / "console.yaml"

    try:
        config = load_config(cfg_path)
    except Exception as e:
        logger.error(f"Failed to load config from {cfg_path}: {e}")
        sys.exit(1)

    host = args.host or config.get("server", {}).get("host", "127.0.0.1")
    port = args.port or config.get("server", {}).get("port", 8088)
    router_cfg = config.get("router", {})
    router_client = RouterClient(
        api_url=router_cfg.get("api_url", "http://127.0.0.1:8080"),
        config_path=router_cfg.get("config_path", "Validation/Data_Router/config/sources.yaml"),
        log_path=router_cfg.get("log_path", "Validation/Data_Router/logs/router.log"),
        state_db_path=router_cfg.get("state_db_path", "Validation/Data_Router/state/router_state.db"),
        workspace_root=workspace_root,
        logger=logger,
    )

    parser_cfg = config.get("parser", {})
    parser_client = ParserClient(api_url=parser_cfg.get("api_url", "http://127.0.0.1:8081"), logger=logger)
    forwarder_cfg = config.get("forwarder", {})
    forwarder_client = ForwarderClient(api_url=forwarder_cfg.get("api_url", "http://127.0.0.1:8082"), logger=logger)

    sc_cfg = config.get("service_control", {})
    ctrl_mode = sc_cfg.get("mode", "auto")
    service_controller = get_service_controller(mode=ctrl_mode, workspace_root=workspace_root)
    logger.info(f"Initialized ServiceController: {service_controller.__class__.__name__}")

    system_status = SystemStatusEvaluator(router_client=router_client, parser_client=parser_client, forwarder_client=forwarder_client)
    console_app_dir = Path(__file__).resolve().parent
    static_dir = console_app_dir / "static"
    template_path = console_app_dir / "templates" / "index.html"
    config_manager = RouterConfigManager(config_path=router_client.config_path, workspace_root=workspace_root, logger=logger)
    database_client = DatabaseClient(workspace_root=workspace_root, logger=logger, service_controller=service_controller, config_manager=config_manager)

    forwarder_service_name = sc_cfg.get("forwarder_service_name", "validation-forwarder.service")
    install_forwarder_web_extension(WebConsoleHandler, workspace_root, service_controller, forwarder_service_name, logger)
    install_router_admin_extension(WebConsoleHandler, workspace_root, config_manager, logger)
    install_database_admin_extension(WebConsoleHandler, workspace_root, service_controller, logger)
    install_filesystem_admin_extension(WebConsoleHandler, logger)

    server = WebConsoleServer(
        host=host,
        port=port,
        router_client=router_client,
        system_status=system_status,
        service_controller=service_controller,
        static_dir=static_dir,
        template_path=template_path,
        router_service_name=sc_cfg.get("router_service_name", "validation-router.service"),
        parser_service_name=sc_cfg.get("parser_service_name", "validation-parser.service"),
        parser_client=parser_client,
        config_manager=config_manager,
        database_client=database_client,
        logger=logger,
    )

    shutdown_event = threading.Event()
    shutting_down = threading.Event()

    def handle_signal(sig, frame):
        if shutting_down.is_set():
            return
        shutting_down.set()
        logger.info(f"Signal {sig} received, shutting down gracefully...")
        try:
            server.shutdown()
        except Exception as exc:
            logger.warning(f"Web Console shutdown warning: {exc}")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    logger.info(f"Starting Validation Web Console on http://{host}:{port}")
    server_thread = threading.Thread(target=server.start, name="WebConsole-HTTP", daemon=True)
    server_thread.start()

    try:
        shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        handle_signal(signal.SIGINT, None)
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server_thread.join(timeout=5)
        logger.info("Validation Web Console stopped")


if __name__ == "__main__":
    main()
