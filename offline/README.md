# Validation Offline Deployment Bundle

This directory is the air-gap package location.

- `python-wheels/` contains Python wheels required to build the Validation image without PyPI access.
- `docker-rpms/` contains Docker Engine, containerd, Buildx, Compose and resolved RPM dependencies for RHEL 9 deployments.
- `docker-debs/` contains Docker Engine, containerd, Buildx, Compose and resolved DEB dependencies for Ubuntu 26.04 deployments.
- `images/` contains the exported Validation Docker image.
- `SHA256SUMS` files verify the transferred artifacts.

The production host does **not** need Python or the Validation Python packages installed on the host. It needs Docker Engine, the Compose plugin, the project files, and the exported Validation image.

For Ubuntu 26.04 x86_64, generate the DEB bundle on an internet-connected Ubuntu 26.04 x86_64 machine using `scripts/download_docker_debs_ubuntu2604.sh`, then transfer `offline/docker-debs/` with the repository and image tar files to the air-gapped host. Install with `scripts/install_offline_ubuntu2604.sh`.

The existing RHEL 9 tooling remains available separately via `scripts/download_docker_rpms_rhel9.sh` and `scripts/install_offline_rhel9.sh`.

## Ubuntu 18.04.3 air-gapped deployment

The production target is Ubuntu 18.04.3 LTS x86_64 with Linux 5.0.0-23-generic.

Do not use the Ubuntu 26.04 DEB bundle on this host. Use the static Docker bundle:

1. On the internet-connected x86_64 machine:
   `bash scripts/download_docker_static_ubuntu1804.sh`
2. Transfer `offline/docker-static/`, `offline/images/`, `offline/python-wheels/`, the repository, and runtime/configuration files to the air-gapped host.
3. On Ubuntu 18.04.3:
   `bash scripts/install_offline_docker_ubuntu1804.sh`
4. Start the stack:
   `docker compose up -d --no-build`

The static Docker bundle uses Docker Engine 24.0.9 and Docker Compose v2.20.2, matching the single-folder offline bundle documented in OFFLINE_DEPLOYMENT.md. The Docker static x86_64 archive is published by Docker; Compose is installed as the Docker CLI plugin.
