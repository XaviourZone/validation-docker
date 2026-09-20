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