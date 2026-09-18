# Offline Docker deployment

The compose stack uses one common Validation image for the parser, router, forwarder and web console. Runtime state and input/output data are mounted outside the image.

## Build

Build the image on a connected build machine:

`docker build -f docker/Dockerfile -t validation/parser:dev .`

For an offline target, export the finalized image:

`docker save validation/parser:dev -o validation-parser-dev.tar`

Transfer the tar and repository deployment bundle to the offline host, then:

`docker load -i validation-parser-dev.tar`
`docker compose up -d`

The runtime directories under `runtime/` are persistent and should be backed up with the deployment.

## Important

The destination configuration is intentionally empty in `docker/forwarder.yaml`. Populate the local offline deployment configuration/secret store before enabling a real downstream destination. Do not commit credentials or private keys.

The VATMS/NAIS TCP sources are disabled in the Docker sample because their actual host/port endpoints are environment-specific. Enable and configure them in `docker/sources.yaml` for the target installation.

This Docker definition is a deployment baseline, not a release acceptance result. The final image must be built only after the 71-task acceptance gate passes.
