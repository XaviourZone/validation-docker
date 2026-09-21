#!/usr/bin/env python3
"""Offline end-to-end Forwarder -> SFTP integration test.

Uses a subprocess-based Paramiko SSH/SFTP server so the client and server
use separate Paramiko transports, matching a real TCP/SSH connection.
No production configuration, credentials, or external network are used.
"""

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import paramiko

from Validation.Data_Forwarder.app.config import (
    DestinationConfig,
    ForwarderConfig,
    RetryConfig,
    SpoolConfig,
)
from Validation.Data_Forwarder.app.secrets import SecretStore
from Validation.Data_Forwarder.app.service import ForwarderService


HOST = "127.0.0.1"
USERNAME = "validation-test"
PASSWORD = "validation-test-password"

_SERVER = r'''
import os, socket, sys, time, traceback, paramiko

HOST = "127.0.0.1"
PORT = int(sys.argv[1])
ROOT = os.path.abspath(sys.argv[2])
USERNAME = "validation-test"
PASSWORD = "validation-test-password"

class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if username == USERNAME and password == PASSWORD else paramiko.AUTH_FAILED
    def get_allowed_auths(self, username):
        return "password"
    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

class SFTP(paramiko.SFTPServerInterface):
    def _p(self, p):
        rel = str(p or "/").replace("\\", "/").lstrip("/")
        target = os.path.realpath(os.path.join(ROOT, rel))
        root = os.path.realpath(ROOT)
        if target != root and not target.startswith(root + os.sep):
            raise OSError("path escapes root")
        return target
    def stat(self, p):
        return paramiko.SFTPAttributes.from_stat(os.stat(self._p(p)))
    def lstat(self, p):
        return paramiko.SFTPAttributes.from_stat(os.lstat(self._p(p)))
    def open(self, p, flags, attr):
        target = self._p(p)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if flags & os.O_TRUNC:
            mode = "wb"
        elif flags & os.O_WRONLY:
            mode = "wb"
        elif flags & os.O_RDWR:
            mode = "r+b"
        elif flags & os.O_APPEND:
            mode = "ab"
        else:
            mode = "rb"
        if flags & os.O_CREAT and not os.path.exists(target):
            open(target, "ab").close()
        try:
            fh = open(target, mode)
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
        h = paramiko.SFTPHandle(flags)
        h.readfile = fh
        h.writefile = fh
        return h
    def remove(self, p):
        try:
            os.unlink(self._p(p)); return paramiko.SFTP_OK
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
    def rename(self, old, new):
        try:
            src, dst = self._p(old), self._p(new)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst); return paramiko.SFTP_OK
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
    def canonicalize(self, p):
        target = self._p(p)
        rel = os.path.relpath(target, ROOT)
        return "/" if rel == "." else "/" + rel.replace(os.sep, "/")

def main():
    os.makedirs(ROOT, exist_ok=True)
    host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, PORT))
    listener.listen(5)
    print("READY " + str(listener.getsockname()[1]), flush=True)
    while True:
        client, _ = listener.accept()
        transport = None
        try:
            transport = paramiko.Transport(client)
            transport.add_server_key(host_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, SFTP)
            transport.start_server(server=Server())
            while transport.is_active():
                time.sleep(0.05)
        except Exception:
            traceback.print_exc()
        finally:
            if transport:
                transport.close()

if __name__ == "__main__":
    main()
'''

class ForwarderDummySFTPTest(unittest.TestCase):
    def test_forwarder_to_dummy_sftp_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix="validation-forwarder-e2e-") as td:
            root = Path(td)
            pending = root / "pending"
            delivered = root / "delivered"
            failed = root / "failed"
            state_db = root / "state" / "forwarder.db"
            secret_file = root / "state" / "forwarder_secrets.json"
            remote = root / "remote"
            for p in (pending, delivered, failed, remote):
                p.mkdir(parents=True, exist_ok=True)

            port_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            port_probe.bind((HOST, 0))
            port = port_probe.getsockname()[1]
            port_probe.close()

            server_script = root / "dummy_sftp_server.py"
            server_script.write_text(_SERVER, encoding="utf-8")
            server = subprocess.Popen(
                [sys.executable, str(server_script), str(port), str(remote)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: server.terminate())
            line = server.stdout.readline().strip()
            self.assertTrue(line.startswith("READY "), f"dummy SFTP did not start: {line!r}")

            SecretStore(secret_file).set("D-DIODE-TEST", PASSWORD)

            config = ForwarderConfig(
                http_host="127.0.0.1",
                http_port=0,
                config_path=root / "forwarder.yaml",
                spool=SpoolConfig(
                    input_dir=pending,
                    archive_dir=delivered,
                    failed_dir=failed,
                    state_db=state_db,
                    secret_file=secret_file,
                    poll_interval_seconds=0.1,
                    claim_timeout_seconds=30,
                ),
                retry=RetryConfig(max_attempts=1, initial_delay_seconds=0, max_delay_seconds=0, multiplier=1),
                destinations={
                    "D-DIODE-TEST": DestinationConfig(
                        name="D-DIODE-TEST",
                        enabled=True,
                        protocol="sftp",
                        host=HOST,
                        port=port,
                        remote_path="/",
                        username=USERNAME,
                        password_file=secret_file,
                        connect_timeout_seconds=5,
                        verify_remote_size=True,
                    )
                },
            )

            service = ForwarderService(config)

            # Isolated test-only client policy: the SFTP server is a freshly
            # generated local test endpoint, so unknown host-key acceptance is
            # safe here. Production transport remains unchanged (RejectPolicy).
            import Validation.Data_Forwarder.app.transport as transport_module
            original_connect = transport_module.SFTPTransport._connect

            def test_connect(destination):
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                kwargs = {
                    "hostname": destination.host,
                    "port": destination.port,
                    "username": destination.username,
                    "password": SecretStore(destination.password_file).get(destination.name),
                    "timeout": destination.connect_timeout_seconds,
                    "banner_timeout": destination.connect_timeout_seconds,
                    "auth_timeout": destination.connect_timeout_seconds,
                }
                try:
                    ssh.connect(**kwargs)
                    return ssh
                except Exception:
                    ssh.close()
                    raise

            transport_module.SFTPTransport._connect = staticmethod(test_connect)
            self.addCleanup(lambda: setattr(transport_module.SFTPTransport, "_connect", original_connect))

            source = pending / "dummy-vessel-001.xml"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Vessel><MMSI>419999999</MMSI><NAME>DUMMY TEST VESSEL</NAME></Vessel>'
            ).encode("utf-8")
            source.write_bytes(xml)

            # process_once() is the synchronous worker operation and only
            # processes files while the service is marked running.
            service.running = True
            try:
                service.process_once()
            finally:
                service.running = False
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)

            remote_file = remote / source.name
            remote_part = remote / (source.name + ".part")
            archived = delivered / source.name
            sha = hashlib.sha256(xml).hexdigest()
            output_id = f"{source.stem}:{sha[:16]}"
            state = service.state.get(output_id, "D-DIODE-TEST")

            self.assertFalse(source.exists())
            self.assertTrue(archived.exists())
            self.assertTrue(remote_file.exists())
            self.assertFalse(remote_part.exists())
            self.assertEqual(remote_file.stat().st_size, len(xml))
            self.assertEqual(remote_file.read_bytes(), xml)
            self.assertEqual(state["state"], "DELIVERED")
            self.assertEqual(state["attempts"], 1)
            self.assertEqual(service.metrics()["states"]["DELIVERED"], 1)

            print("PASS: Forwarder -> dummy SSH/SFTP -> remote folder")
            print(f"PASS: dummy SFTP port {port}")
            print("PASS: remote size verification")
            print("PASS: atomic .part -> final rename")
            print("PASS: local pending -> delivered archive")
            print("PASS: persistent state DELIVERED")

if __name__ == "__main__":
    unittest.main(verbosity=2)
