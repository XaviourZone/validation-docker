#!/usr/bin/env python3
"""Offline end-to-end Forwarder -> SFTP integration test.

Starts an in-process Paramiko SSH/SFTP server on 127.0.0.1 using a random
high port, creates a dummy XML in the Forwarder pending spool, runs one
ForwarderService cycle, and verifies:
  * SFTP connection succeeds with strict host-key checking.
  * XML is uploaded to the remote directory.
  * remote size matches.
  * .part is renamed to the final file.
  * local pending XML is archived.
  * persistent Forwarder state is DELIVERED.
  * no real docker/forwarder.yaml/runtime data is modified.

No external network and no real credentials are used.
"""

import hashlib
import os
import socket
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


class DummySSHServer(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        if username == USERNAME and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class LocalSFTPInterface(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, root=None, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.root = Path(root).resolve()

    def _path(self, path):
        raw = str(path or "/").replace("\\", "/")
        relative = raw.lstrip("/")
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise OSError("path escapes dummy SFTP root")
        return candidate

    def stat(self, path):
        return paramiko.SFTPAttributes.from_stat(os.stat(self._path(path)))

    def lstat(self, path):
        return paramiko.SFTPAttributes.from_stat(os.lstat(self._path(path)))

    def open(self, path, flags, attr):
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b"
        if flags & os.O_WRONLY:
            mode = "wb"
        elif flags & os.O_RDWR:
            mode = "r+b"
        if flags & os.O_APPEND:
            mode = "ab"
        if flags & os.O_CREAT and not target.exists():
            target.touch()
        if flags & os.O_TRUNC:
            mode = "wb"
        try:
            fh = open(target, mode)
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = fh
        handle.writefile = fh
        return handle

    def remove(self, path):
        try:
            self._path(path).unlink()
            return paramiko.SFTP_OK
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def rename(self, oldpath, newpath):
        try:
            old = self._path(oldpath)
            new = self._path(newpath)
            new.parent.mkdir(parents=True, exist_ok=True)
            os.replace(old, new)
            return paramiko.SFTP_OK
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def canonicalize(self, path):
        try:
            target = self._path(path)
            return "/" + target.relative_to(self.root).as_posix()
        except Exception:
            return "/"


class DummySFTPServer:
    def __init__(self, root):
        self.root = Path(root)
        self.host_key = paramiko.RSAKey.generate(2048)
        self.ready = threading.Event()
        self.stop_event = threading.Event()
        self.error = None
        self.port = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("dummy SFTP server did not start")
        if self.error:
            raise self.error

    def _run(self):
        transport = None
        listener = None
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, 0))
            listener.listen(5)
            listener.settimeout(0.5)
            self.port = listener.getsockname()[1]
            self._listener = listener
            self.ready.set()

            while not self.stop_event.is_set():
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                transport = paramiko.Transport(client)
                transport.add_server_key(self.host_key)
                transport.set_subsystem_handler(
                    "sftp",
                    paramiko.SFTPServer,
                    LocalSFTPInterface,
                    root=str(self.root),
                )
                server = DummySSHServer()
                transport.start_server(server=server)
                while transport.is_active() and not self.stop_event.is_set():
                    time.sleep(0.05)
                transport.close()
                transport = None
        except Exception as exc:
            self.error = exc
            self.ready.set()
        finally:
            if transport:
                transport.close()
            if listener:
                listener.close()

    def stop(self):
        self.stop_event.set()
        try:
            with socket.create_connection((HOST, self.port), timeout=0.5):
                pass
        except OSError:
            pass
        self.thread.join(timeout=5)


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
            pending.mkdir()
            delivered.mkdir()
            failed.mkdir()
            remote.mkdir()

            server = DummySFTPServer(remote)
            server.start()
            self.addCleanup(server.stop)

            ssh_dir = root / "ssh"
            ssh_dir.mkdir()
            known_hosts = ssh_dir / "known_hosts"
            hosts = paramiko.HostKeys()
            hosts.add(f"[{HOST}]:{server.port}", server.host_key.get_name(), server.host_key)
            hosts.save(str(known_hosts))

            # Paramiko's SSHClient.load_system_host_keys() follows HOME/.ssh/known_hosts.
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = str(root)
            (root / ".ssh").mkdir()
            known_hosts.replace(root / ".ssh" / "known_hosts")
            self.addCleanup(
                lambda: os.environ.__setitem__("HOME", old_home)
                if old_home is not None
                else os.environ.pop("HOME", None)
            )

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
                retry=RetryConfig(
                    max_attempts=1,
                    initial_delay_seconds=0,
                    max_delay_seconds=0,
                    multiplier=1,
                ),
                destinations={
                    "D-DIODE-TEST": DestinationConfig(
                        name="D-DIODE-TEST",
                        enabled=True,
                        protocol="sftp",
                        host=HOST,
                        port=server.port,
                        remote_path="/",
                        username=USERNAME,
                        password_file=secret_file,
                        connect_timeout_seconds=5,
                        verify_remote_size=True,
                    )
                },
            )

            service = ForwarderService(config)
            self.addCleanup(service.stop)

            source = pending / "dummy-vessel-001.xml"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Vessel><MMSI>419999999</MMSI>'
                '<NAME>DUMMY TEST VESSEL</NAME></Vessel>'
            ).encode("utf-8")
            source.write_bytes(xml)

            service.process_once()

            remote_file = remote / source.name
            remote_part = remote / (source.name + ".part")
            archived = delivered / source.name
            sha = hashlib.sha256(xml).hexdigest()
            output_id = f"{source.stem}:{sha[:16]}"
            state = service.state.get(output_id, "D-DIODE-TEST")

            self.assertFalse(source.exists(), "pending XML must be archived after delivery")
            self.assertTrue(archived.exists(), "delivered archive XML is missing")
            self.assertTrue(remote_file.exists(), "remote SFTP XML is missing")
            self.assertFalse(remote_part.exists(), ".part file must not remain")
            self.assertEqual(remote_file.stat().st_size, len(xml))
            self.assertEqual(remote_file.read_bytes(), xml)
            self.assertEqual(state["state"], "DELIVERED")
            self.assertEqual(state["attempts"], 1)
            self.assertEqual(service.metrics()["states"]["DELIVERED"], 1)

            print("PASS: Forwarder -> dummy SSH/SFTP -> remote folder")
            print(f"PASS: SFTP port {server.port}")
            print("PASS: remote size verification")
            print("PASS: atomic .part -> final rename")
            print("PASS: local pending -> delivered archive")
            print("PASS: persistent state DELIVERED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
