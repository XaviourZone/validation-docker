# Validation Offline Deployment Bundle

This directory is the air-gap package location.

- `python-wheels/` contains Python wheels required to build the Validation image without PyPI access.
- `docker-rpms/` contains Docker Engine, containerd, Buildx, Compose and resolved RPM dependencies.
- `images/` contains the exported Validation Docker image.
- `SHA256SUMS` files verify the transferred artifacts.

The production host does **not** need Python or the Validation Python packages installed on the host. It needs Docker Engine, the Compose plugin, the project files, and the exported Validation image.

For the current deployment tooling the Docker RPM target is RHEL 9 x86_64. Generate the RPM bundle on an internet-connected machine matching the production OS and architecture.

Docker's official RHEL documentation supports RHEL 8, 9 and 10 and documents offline RPM installation.