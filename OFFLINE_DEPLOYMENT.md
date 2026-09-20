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
- loads the prebuilt Validation image;
- creates the runtime directories;
- starts the complete stack with `--no-build`;
- does not pull anything from the Internet.

## Subsequent starts

After the first installation:

```bash
cd validation-offline-ubuntu1804
sudo ./install/install_and_start.sh
```

or:

```bash
./install/install_and_start.sh
```

For a normal restart without reinstalling Docker:

```bash
./project/scripts/start_offline.sh
```

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
