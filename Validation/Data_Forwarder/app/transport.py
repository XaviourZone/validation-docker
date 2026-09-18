from pathlib import Path
import shutil

from .config import DestinationConfig
from .secrets import SecretStore


class DeliveryError(Exception):
    pass


class Transport:
    def deliver(self, source: Path, destination: DestinationConfig) -> None:
        raise NotImplementedError

    def test_connection(self, destination: DestinationConfig) -> None:
        return None


class FilesystemTransport(Transport):
    def deliver(self, source: Path, destination: DestinationConfig) -> None:
        if not destination.remote_path:
            raise DeliveryError("filesystem destination remote_path is empty")
        target_dir = Path(destination.remote_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        temp = target.with_name(target.name + ".part")
        shutil.copyfile(source, temp)
        temp.replace(target)
        if destination.verify_remote_size and target.stat().st_size != source.stat().st_size:
            target.unlink(missing_ok=True)
            raise DeliveryError("filesystem transfer size verification failed")

    def test_connection(self, destination: DestinationConfig) -> None:
        if not destination.remote_path:
            raise DeliveryError("filesystem destination remote_path is empty")
        Path(destination.remote_path).mkdir(parents=True, exist_ok=True)


class SFTPTransport(Transport):
    def _connect(self, destination: DestinationConfig):
        try:
            import paramiko
        except ImportError as exc:
            raise DeliveryError("Paramiko is required for SFTP delivery") from exc
        if not destination.host or not destination.remote_path or not destination.username:
            raise DeliveryError("SFTP destination requires host, username and remote_path")

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            kwargs = {
                "hostname": destination.host,
                "port": destination.port or 22,
                "username": destination.username,
                "timeout": destination.connect_timeout_seconds,
                "banner_timeout": destination.connect_timeout_seconds,
                "auth_timeout": destination.connect_timeout_seconds,
            }
            if destination.private_key_file:
                key = paramiko.RSAKey.from_private_key_file(destination.private_key_file)
                kwargs["pkey"] = key
            else:
                password = SecretStore(destination.password_file).get(destination.name)
                if not password:
                    raise DeliveryError("SFTP password is not configured")
                kwargs["password"] = password
            ssh.connect(**kwargs)
            return ssh
        except DeliveryError:
            ssh.close()
            raise
        except Exception as exc:
            ssh.close()
            raise DeliveryError(f"SFTP connection failed: {exc}") from exc

    def deliver(self, source: Path, destination: DestinationConfig) -> None:
        ssh = self._connect(destination)
        remote_dir = destination.remote_path.rstrip("/")
        remote_file = f"{remote_dir}/{source.name}"
        try:
            with ssh.open_sftp() as sftp:
                sftp.stat(remote_dir)
                temp = remote_file + ".part"
                sftp.put(str(source), temp)
                if destination.verify_remote_size and sftp.stat(temp).st_size != source.stat().st_size:
                    try:
                        sftp.remove(temp)
                    except OSError:
                        pass
                    raise DeliveryError("SFTP transfer size verification failed")
                sftp.rename(temp, remote_file)
        except DeliveryError:
            raise
        except Exception as exc:
            raise DeliveryError(f"SFTP delivery failed: {exc}") from exc
        finally:
            ssh.close()

    def test_connection(self, destination: DestinationConfig) -> None:
        ssh = self._connect(destination)
        try:
            with ssh.open_sftp() as sftp:
                sftp.stat(destination.remote_path)
        except Exception as exc:
            raise DeliveryError(f"SFTP remote path check failed: {exc}") from exc
        finally:
            ssh.close()


def transport_for(destination: DestinationConfig) -> Transport:
    if destination.protocol == "filesystem":
        return FilesystemTransport()
    if destination.protocol == "sftp":
        return SFTPTransport()
    raise DeliveryError(f"Unsupported delivery protocol: {destination.protocol}")
