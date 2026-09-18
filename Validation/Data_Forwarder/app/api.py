import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_server(host, port, service):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload, code=200):
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            if self.path == "/health":
                self._send({"status": "READY", "service": "data-forwarder", "running": service.running})
            elif self.path == "/metrics":
                self._send(service.metrics())
            elif self.path == "/deliveries":
                self._send({"deliveries": service.state.recent()})
            elif self.path == "/config/destinations":
                self._send({"destinations": service.destinations_view()})
            else:
                self._send({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/config/destinations/save":
                    self._send(service.save_destination(body))
                    return
                if self.path == "/config/reload":
                    service.reload_config()
                    self._send({"success": True, "message": "Configuration reloaded"})
                    return
                if self.path == "/config/destinations/test":
                    name = str(body.get("name", ""))
                    self._send(service.test_destination(name))
                    return
                match = re.match(r"^/config/destinations/([^/]+)/(delete|enable|disable)$", self.path)
                if match:
                    name, action = match.groups()
                    if action == "delete":
                        self._send(service.delete_destination(name))
                    else:
                        dest = service.config.destinations.get(name)
                        if not dest:
                            raise KeyError(f"Destination '{name}' not found")
                        service.save_destination({
                            "name": name,
                            "enabled": action == "enable",
                            "protocol": dest.protocol,
                            "host": dest.host,
                            "port": dest.port,
                            "remote_path": dest.remote_path,
                            "username": dest.username,
                            "private_key_file": dest.private_key_file,
                            "connect_timeout_seconds": dest.connect_timeout_seconds,
                            "verify_remote_size": dest.verify_remote_size,
                        })
                        self._send({"success": True, "destination": name, "enabled": action == "enable"})
                    return
                self._send({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except KeyError as exc:
                self._send({"success": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send({"success": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def log_message(self, fmt, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)
