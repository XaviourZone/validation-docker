"""Automated tests for Validation Web Console covering all 17 specified scenarios using standard unittest."""

import json
import os
import re
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch
import yaml

from Validation.Web_Console.app.router_client import RouterClient
from Validation.Web_Console.app.server import WebConsoleHandler, WebConsoleServer
from Validation.Web_Console.app.service_control.base import BaseServiceController
from Validation.Web_Console.app.service_control.linux import LinuxSystemdController
from Validation.Web_Console.app.service_control.windows import WindowsDevelopmentController
from Validation.Web_Console.app.service_control.factory import get_service_controller
from Validation.Web_Console.app.system_status import SystemStatusEvaluator


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(url: str, timeout: float = 3.0):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()


def http_post(url: str, data: dict = None, timeout: float = 3.0):
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8")) if e.fp else {}
        return e.code, body


class TestWebConsole(unittest.TestCase):
    """Test suite covering all 17 mandatory Web Console requirements."""

    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.host = "127.0.0.1"

        cls.workspace_root = Path(__file__).resolve().parent.parent.parent.parent
        cls.console_dir = cls.workspace_root / "Validation" / "Web_Console"
        cls.static_dir = cls.console_dir / "app" / "static"
        cls.template_path = cls.console_dir / "app" / "templates" / "index.html"

        cls.router_client = RouterClient(
            api_url="http://127.0.0.1:58999",  # Unreachable by default to test offline resilience
            config_path="Validation/Data_Router/config/sources.yaml",
            log_path="Validation/Data_Router/logs/router.log",
            state_db_path="Validation/Data_Router/state/router_state.db",
            workspace_root=cls.workspace_root,
        )
        cls.system_status = SystemStatusEvaluator(router_client=cls.router_client)
        cls.service_ctrl = WindowsDevelopmentController(workspace_root=cls.workspace_root)

        cls.server = WebConsoleServer(
            host=cls.host,
            port=cls.port,
            router_client=cls.router_client,
            system_status=cls.system_status,
            service_controller=cls.service_ctrl,
            static_dir=cls.static_dir,
            template_path=cls.template_path,
        )

        cls.thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.thread.start()
        time.sleep(0.3)  # Wait for socket bind
        cls.base_url = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    # 1. Dashboard loads
    def test_01_dashboard_loads(self):
        status, headers, body = http_get(f"{self.base_url}/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("Validation Maritime Operations Console", html)
        self.assertIn("radar-logo", html)
        self.assertIn("console.css", html)
        self.assertIn("console.js", html)

    # 2. Router status is retrieved
    def test_02_router_status_retrieved(self):
        status, headers, body = http_get(f"{self.base_url}/api/router/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("service", data)
        self.assertIn("overall_status", data)
        self.assertIn("queue_health", data)

    # 3. Router metrics are retrieved
    def test_03_router_metrics_retrieved(self):
        status, headers, body = http_get(f"{self.base_url}/api/router/metrics")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue("totals" in data or "uptime_seconds" in data)

    # 4. Router source list is displayed
    def test_04_router_source_list(self):
        status, headers, body = http_get(f"{self.base_url}/api/router/sources")
        self.assertEqual(status, 200)
        sources = json.loads(body.decode("utf-8"))
        self.assertIsInstance(sources, list)
        source_names = [s["source_name"] for s in sources]
        for expected in ["SAIS_IOR", "SAIS_GLOBAL", "MSIS", "LRIT", "VATMS_EAST", "VATMS_WEST", "NAIS"]:
            self.assertIn(expected, source_names)

    # 5. Router unavailable scenario
    def test_05_router_unavailable_scenario(self):
        status, headers, body = http_get(f"{self.base_url}/api/router/health")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertFalse(data["reachable"])
        self.assertEqual(data["status"], "OFFLINE")

    # 6. Parser unavailable/not implemented scenario
    def test_06_parser_unimplemented_scenario(self):
        status, headers, body = http_get(f"{self.base_url}/api/system/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        modules = {m["id"]: m for m in data["modules"]}
        self.assertIn(modules["parser"]["status"], ("NOT IMPLEMENTED", "NOT RUNNING", "STOPPED"))
        self.assertEqual(modules["forwarder"]["status"], "NOT IMPLEMENTED")

        # Verify /api/parser/status and /api/parser/metrics respond cleanly
        p_status, _, p_body = http_get(f"{self.base_url}/api/parser/status")
        self.assertEqual(p_status, 200)
        p_data = json.loads(p_body.decode("utf-8"))
        self.assertIn("service", p_data)
        self.assertIn("validation-data-parser", p_data["service"])

        m_status, _, m_body = http_get(f"{self.base_url}/api/parser/metrics")
        self.assertEqual(m_status, 200)
        m_data = json.loads(m_body.decode("utf-8"))
        self.assertIn("messages_received", m_data)

    # 7. Invalid API response / bad endpoint
    def test_07_invalid_endpoint_response(self):
        try:
            urllib.request.urlopen(f"{self.base_url}/api/router/unknown_endpoint")
            self.fail("Should have raised HTTP 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            data = json.loads(e.read().decode("utf-8"))
            self.assertTrue(data.get("error"))

    # 8. Control endpoint success
    def test_08_control_endpoint_success(self):
        status, data = http_post(f"{self.base_url}/api/router/validate-config")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("valid"))
        self.assertGreaterEqual(data.get("source_count", 0), 7)

    # 9. Control endpoint failure / validation failure
    def test_09_control_endpoint_validation_failure(self):
        original_cfg = self.router_client.config_path
        self.router_client.config_path = Path("non_existent_config.yaml")
        try:
            status, data = http_post(f"{self.base_url}/api/router/validate-config")
            self.assertEqual(status, 400)
            self.assertFalse(data.get("valid"))
        finally:
            self.router_client.config_path = original_cfg

    # 10. Unauthorized/invalid control request
    def test_10_invalid_control_request(self):
        status, data = http_post(f"{self.base_url}/api/router/execute-arbitrary-command")
        self.assertEqual(status, 404)

    # 11. Windows development mode controller
    def test_11_windows_dev_mode_controller(self):
        ctrl = WindowsDevelopmentController(workspace_root=self.workspace_root)
        status = ctrl.get_service_status("validation-router.service")
        self.assertIn("status", status)
        self.assertEqual(status["mode"], "windows_development")
        res = ctrl.reload_configuration("validation-router.service")
        self.assertTrue(res.get("success"))

    # 12. Linux / systemd mode abstraction
    def test_12_linux_systemd_controller_abstraction(self):
        ctrl = LinuxSystemdController()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ActiveState=active\nSubState=running\nMainPID=1234\n", stderr=""
            )
            status = ctrl.get_service_status("validation-router.service")
            self.assertEqual(status["status"], "RUNNING")
            self.assertEqual(status["pid"], 1234)

            ctrl.stop_service("validation-router.service")
            mock_run.assert_called_with(
                ["systemctl", "stop", "validation-router.service"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
            )

    # 13. Configuration loading
    def test_13_configuration_loading(self):
        cfg_file = self.workspace_root / "Validation" / "Web_Console" / "config" / "console.yaml"
        self.assertTrue(cfg_file.exists())
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.assertEqual(cfg["server"]["port"], 8088)
        self.assertIn("validation-router.service", cfg["service_control"]["router_service_name"])

    # 14. No hard-coded Windows paths
    def test_14_no_hardcoded_windows_paths(self):
        code_files = list((self.console_dir / "app").rglob("*.py"))
        self.assertGreater(len(code_files), 0)
        windows_path_regex = re.compile(r'[a-zA-Z]:\\')

        for py_file in code_files:
            content = py_file.read_text(encoding="utf-8")
            matches = windows_path_regex.findall(content)
            self.assertEqual(len(matches), 0, f"Found hardcoded Windows path in {py_file}: {matches}")

    # 15. Offline frontend loads without Internet
    def test_15_offline_frontend_no_external_urls(self):
        html = (self.console_dir / "app" / "templates" / "index.html").read_text(encoding="utf-8")
        css = (self.console_dir / "app" / "static" / "css" / "console.css").read_text(encoding="utf-8")
        js = (self.console_dir / "app" / "static" / "js" / "console.js").read_text(encoding="utf-8")

        external_url_pattern = re.compile(r'https?://(?!127\.0\.0\.1|localhost)[^\s"\'>]+')
        for name, text in [("index.html", html), ("console.css", css), ("console.js", js)]:
            external_urls = external_url_pattern.findall(text)
            self.assertEqual(len(external_urls), 0, f"Found external URL in {name}: {external_urls}")

        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("cdnjs", html)
        self.assertNotIn("unpkg", html)

    # 16. Service restart / recovery handling
    def test_16_service_restart_recovery(self):
        with patch.object(self.router_client, "_http_get") as mock_get:
            mock_get.return_value = {
                "service": "validation-data-router",
                "overall_status": "OPERATIONAL",
                "queue_health": {"status": "HEALTHY", "current_depth": 5},
                "metrics": {"uptime_seconds": 45.0, "totals": {"received": 12, "acknowledged": 12, "failed": 0}}
            }
            status, _, body = http_get(f"{self.base_url}/api/router/status")
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data["overall_status"], "OPERATIONAL")
            self.assertEqual(data["queue_health"]["current_depth"], 5)

            sys_status, _, sys_body = http_get(f"{self.base_url}/api/system/status")
            sys_data = json.loads(sys_body.decode("utf-8"))
            self.assertEqual(sys_data["overall_health"], "HEALTHY")

    # 17. Concurrent status polling
    def test_17_concurrent_polling(self):
        urls = [
            f"{self.base_url}/api/system/status",
            f"{self.base_url}/api/router/status",
            f"{self.base_url}/api/router/sources",
            f"{self.base_url}/api/router/queue",
        ]
        results = []

        def worker(u):
            try:
                code, _, _ = http_get(u, timeout=5.0)
                results.append(code)
            except Exception as e:
                results.append(str(e))

        threads = [threading.Thread(target=worker, args=(urls[i % len(urls)],)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(len(results), 20)
        self.assertTrue(all(code == 200 for code in results), f"Expected all 200s, got: {results}")

    # 18. Config & Parser Destinations endpoint
    def test_18_get_router_config_and_destinations(self):
        status, _, body = http_get(f"{self.base_url}/api/router/parser-destinations")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("SAIS", data)
        self.assertIn("VATMS", data)

        cfg_status, _, cfg_body = http_get(f"{self.base_url}/api/router/config")
        self.assertEqual(cfg_status, 200)
        cfg_data = json.loads(cfg_body.decode("utf-8"))
        self.assertIn("sources", cfg_data)
        self.assertIn("parser_destinations", cfg_data)

    # 19. Source validation endpoint
    def test_19_source_validation_endpoint(self):
        # Valid payload
        valid_payload = {
            "source_name": "TEST_VALID_API",
            "type": "file",
            "parser": "SAIS",
            "folder": "TEST_VALID_API",
            "is_new": True,
        }
        status, body = http_post(f"{self.base_url}/api/router/sources/validate", valid_payload)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("valid"))

        # Invalid payload (missing folder)
        invalid_payload = {
            "source_name": "TEST_INVALID_API",
            "type": "file",
            "parser": "SAIS",
            "folder": "",
            "is_new": True,
        }
        bad_status, bad_body = http_post(f"{self.base_url}/api/router/sources/validate", invalid_payload)
        self.assertEqual(bad_status, 422)
        self.assertFalse(bad_body.get("valid"))
        self.assertTrue(len(bad_body.get("errors", [])) > 0)

    # 20. Source save and delete endpoints
    def test_20_source_save_and_delete_endpoints(self):
        # Save a new source
        save_payload = {
            "source_name": "API_TEMP_SRC",
            "type": "file",
            "parser": "MSIS",
            "folder": "API_TEMP_SRC",
            "is_new": True,
        }
        status, body = http_post(f"{self.base_url}/api/router/sources/save", save_payload)
        self.assertEqual(status, 200)
        self.assertTrue(body.get("success"))
        self.assertTrue(body.get("reload_required"))

        # Verify source appears in /api/router/sources
        src_status, _, src_body = http_get(f"{self.base_url}/api/router/sources")
        sources = json.loads(src_body.decode("utf-8"))
        self.assertTrue(any(s["source_name"] == "API_TEMP_SRC" for s in sources))

        # Delete the source
        del_status, del_body = http_post(f"{self.base_url}/api/router/sources/API_TEMP_SRC/delete", {})
        self.assertEqual(del_status, 200)
        self.assertTrue(del_body.get("success"))

        # Verify source is removed
        _, _, verify_body = http_get(f"{self.base_url}/api/router/sources")
        verified_sources = json.loads(verify_body.decode("utf-8"))
        self.assertFalse(any(s["source_name"] == "API_TEMP_SRC" for s in verified_sources))

    # 21. Audit log endpoint
    def test_21_audit_log_endpoint(self):
        status, _, body = http_get(f"{self.base_url}/api/router/audit")
        self.assertEqual(status, 200)
        audit_records = json.loads(body.decode("utf-8"))
        self.assertIsInstance(audit_records, list)

    # 22. HTML markup contains simplified router controls and modals
    def test_22_ui_markup_has_tooltips_and_modals(self):
        status, _, body = http_get(f"{self.base_url}/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        # Check start button tooltip
        self.assertIn('data-tooltip="Start the Data Router service."', html)
        # Verify removed controls are NOT present on Router page per Section 6
        self.assertNotIn('data-tooltip="Gracefully stop the Data Router service."', html)
        self.assertNotIn('data-tooltip="Stop and start the Data Router service."', html)
        self.assertNotIn('data-tooltip="Reload the Data Router configuration.', html)
        # Check modals
        self.assertIn('id="modal-source-config"', html)
        self.assertIn('id="modal-confirmation"', html)
        self.assertIn('Add Data Source', html)


if __name__ == "__main__":
    unittest.main()
