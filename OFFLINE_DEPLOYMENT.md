# Offline Deployment — Ubuntu 18.04.3

## Target

This deployment bundle is designed for an **x86_64 Ubuntu 18.04.3 offline VM** where Python and Internet access are unavailable.

The target VM does **not** need Python or pip.

Python and the application's Python dependencies are already inside the Docker image.

## Build the offline bundle on the connected machine

From the Validation repository:

```bash
cd ~/Documents/validation-docker
chmod +x scripts/create_offline_bundle.sh
./scripts/create_offline_bundle.sh
```

The script:

1. Builds `validation/parser:dev`.
2. Includes Parser, Router, Forwarder, Database and Web Console Python dependencies in that image.
3. Saves the image as a Docker tar archive.
4. Copies the project/configuration into the bundle.
5. Downloads Docker Engine 24.0.9 static binaries for x86_64.
6. Downloads Docker Compose v2.20.2.
7. Creates SHA256 checksums.
8. Creates the target-side installer/start script.

The result is one folder:

```text
validation-offline-ubuntu1804/
├── image/
│   └── validation-parser-dev.tar
├── docker-runtime/
│   ├── docker-24.0.9.tgz
│   └── docker-compose-linux-x86_64
├── project/
│   └── Validation project
├── install/
│   └── install_and_start.sh
└── SHA256SUMS
```

Copy this **single folder** to the offline VM.

## First installation on the offline VM

```bash
cd validation-offline-ubuntu1804
sudo ./install/install_and_start.sh
```

The installer:

- installs the bundled Docker static binaries;
- installs the bundled Compose plugin;
- creates/starts a systemd Docker service;
- enables Docker to start at host boot;
- loads the prebuilt Validation image;
- creates the runtime directories;
- starts the complete stack with `--no-build`;
- does not pull anything from the Internet.

All Validation services use `restart: unless-stopped`, so after a normal VM reboot, Docker will bring the existing containers back up automatically.

## Normal operation after installation

For a normal start/restart, use:

```bash
cd validation-offline-ubuntu1804
sudo ./project/scripts/start_offline.sh
```

This starts the existing stack with:

```text
docker compose up -d --no-build
```

It does **not** build, pull, or force-recreate the containers.

If the VM is shut down and later powered on again, the Docker service starts automatically and the Validation containers are configured to restart.

## Existing runtime state

The persistent runtime state is kept under:

```text
validation-offline-ubuntu1804/project/runtime/
```

This includes the configured runtime databases/state, router state/logs, parser state/logs, forwarder state, spool directories and reference data mounted by the services.

Stopping or rebooting the VM does not intentionally delete this state.

Do **not** delete the `project/runtime/` directory if the existing operational state needs to be retained.

## Host folder selection

The Web Console Data Router provides operator folder browsing/configuration.

The Router and Web Console expose the host filesystem inside the containers at:

```text
/opt/validation/hostfs
```

with the host root mapped from `/`.

The Router host-filesystem mount is writable because file-source lifecycle requires the Router to delete an input file after the Parser has acknowledged it.

A selected absolute host folder is translated to the corresponding path inside the container and can be monitored by the Router. For file sources, after a successful Parser ACK, the original input file is deleted immediately. No `processed/` copy or archive is retained. If delivery to the Parser fails or retries are exhausted without a successful ACK, the original input file remains available for retry/operator handling.

Because the Router has write access to the host filesystem mount, this deployment should be treated as an isolated operational VM. Configure Router source folders only for directories that Validation is intended to read and finalize.

## Services

After startup:

- Web Console: http://localhost:8088
- Data Router API: http://localhost:8080
- Data Parser API: http://localhost:8081
- Data Forwarder API: http://localhost:8082

## Important

Ubuntu 18.04.3 is an old, end-of-life operating system and current Docker documentation no longer lists it among supported Ubuntu releases. This bundle therefore uses a **static Docker Engine deployment** rather than relying on the current Docker apt repository.

The target must be x86_64/amd64 and must have the normal Linux prerequisites needed by Docker, including a suitable kernel, `iptables`, and `ps`.

This bundle is intended for the isolated/offline legacy environment. It should not be treated as a replacement for upgrading the host OS when that is operationally possible.
