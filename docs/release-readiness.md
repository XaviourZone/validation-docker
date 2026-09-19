# Validation Docker — Release Readiness

## Repository state

Branch: dev/validation-full-build

The implementation has reached the repository-complete stage. The latest pre-hardening acceptance gate passed 6/6, and the final hardening changes have expanded the gate further.

## Completed implementation

- Canonical 41-field XML contract and deterministic XML generation.
- Source-specific SAIS, MSIS, LRIT, VATMS and NAIS parsing.
- Normalization, validation, correlation, reference enrichment architecture and XML generation.
- Router transport-only boundary.
- Persistent Router file state, hashing, stable-file detection and restart recovery.
- Bounded routing queue and retry/ACK/NACK handling.
- Forwarder spool, persistent delivery state, retry and archive boundary.
- Docker Compose service topology and persistent runtime volumes.
- Web Console source-folder and file-pattern configuration.
- Offline Docker image export/load tooling.
- Full validation gate with parser, Router, pipeline, Docker and offline-image checks.
- Explicit VATMS/NAIS control-message tests.
- Focused Task 62 file-source lifecycle tests.

## Acceptance evidence

The latest post-hardening gate passed **12/12** in GitHub Actions run **94**, job **105874005822**.

The passing gate covered:

- reference DB importer tests for WRS/PANS/NSC
- lookup/fallback semantic tests
- real-source parser test structure
- Web Console configuration tests
- Router → Parser → Forwarder end-to-end acceptance
- Router lifecycle/recovery tests
- XML field-coverage tests
- Docker Compose syntax and image build
- offline image save/load
- deployed Compose Parser/Router/Forwarder/Web restart/recovery
- release-document consistency

The deployed Compose restart/recovery test physically started the service stack, verified Parser /health, Router /status, Forwarder /health and Web availability, restarted all four services, verified recovery again, and cleaned up.

## Remaining environment-dependent acceptance

The repository-side implementation and automated gate are complete, but the following still require authoritative deployment material:

1. Real WRS/PANS/NSC operational databases and representative rows.
2. Real production SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS and NAIS datasets for measured coverage.
3. Authoritative iTrackLib source/contract for exact maximum string lengths.
4. One target-host offline deployment smoke test using the actual mounted reference/data directories.

These are evidence inputs, not unimplemented software. No production enrichment result, production record count, or maximum-length value is inferred without the authoritative source.

## Release rule

Do not create a release/version tag until the environment-dependent acceptance evidence above is captured. Once those checks pass, the branch can be frozen for release.


## Real-data acceptance runner

The repository now includes `scripts/real_data_acceptance.py`, which builds isolated WRS/PANS/NSC databases from a supplied data tree, runs the actual reference lookup and `PipelineProcessor` against SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS_EAST, VATMS_WEST and NAIS, and produces XML field coverage plus throughput/rejection measurements. See `docs/real-data-acceptance.md`. This keeps operational data out of Git while making the final acceptance reproducible.
