import argparse
import logging
import os
import signal
import threading
from pathlib import Path

from .api import make_server
from .config import load_config
from .service import ForwarderService


def project_root():
    value = os.environ.get("VALIDATION_HOME")
    if value:
        return Path(value).resolve()
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "Validation").is_dir():
            return parent
    return Path.cwd()


def main():
    parser = argparse.ArgumentParser(description="Validation Data Forwarder")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    root = project_root()
    config_path = Path(args.config) if args.config else root / "Validation/Data_Forwarder/config/forwarder.yaml"
    if not config_path.is_absolute():
        config_path = root / config_path

    cfg = load_config(config_path, root)
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO), format="[%(asctime)s] [%(levelname)s] [DATA_FORWARDER] %(message)s")
    log = logging.getLogger("forwarder")
    service = ForwarderService(cfg, log)
    api = make_server(cfg.http_host, cfg.http_port, service)
    api_thread = threading.Thread(target=api.serve_forever, name="Forwarder-API", daemon=True)
    shutdown_event = threading.Event()
    shutting_down = threading.Event()

    def shutdown(signum=None, frame=None):
        if shutting_down.is_set():
            return
        shutting_down.set()
        if signum is not None:
            log.info("Signal %s received", signum)
        else:
            log.info("Shutdown requested")
        service.stop()
        try:
            api.shutdown()
        except Exception:
            pass
        shutdown_event.set()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    service.start()
    api_thread.start()
    log.info("Data Forwarder listening on %s:%s", cfg.http_host, cfg.http_port)
    try:
        # signal.pause() is Unix-only. Event.wait() keeps the same blocking
        # behavior and works on Windows and Ubuntu.
        shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        shutdown()
    finally:
        service.stop()
        try:
            api.shutdown()
        except Exception:
            pass
        api.server_close()
        api_thread.join(timeout=5)
        log.info("Data Forwarder stopped")


if __name__ == "__main__":
    main()
