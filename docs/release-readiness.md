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

## Acceptance evidence already captured

The latest pre-hardening gate recorded:

    VALIDATION GATE: 6/6 steps passed

The full pipeline acceptance covered:

    SAIS_IOR file
      -> Router
      -> real Parser TCP endpoint
      -> parsing/normalization/validation/correlation/enrichment pipeline
      -> XML
      -> Forwarder pending spool
      -> filesystem delivery

Router integration/recovery covered:

- stable file detection
- duplicate suppression
- persistent state
- restart semantics
- downstream retry
- TCP reconnect

## Final post-change gate

Run from the repository root on the prepared Ubuntu/offline host:

    ./scripts/run_validation_gate.sh

If the shell wrapper is not executable in the checkout:

    chmod +x scripts/run_validation_gate.sh
    ./scripts/run_validation_gate.sh

The Docker portion now additionally validates:

- Compose syntax
- image build
- Docker image save
- Docker image load

## Evidence that cannot be fabricated in a clean repository

The following require authoritative operational material that is intentionally not committed:

1. Real WRS/PANS/NSC databases and representative rows.
2. Real production SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS and NAIS datasets.
3. The authoritative iTrackLib source/contract required to establish exact maximum string lengths.
4. A complete deployed-Compose restart/recovery exercise on the target host.

These are environment-dependent acceptance inputs, not missing software architecture.

No production enrichment result, production record count, or maximum-length value is inferred without the authoritative source.

## Release rule

Do not create a release/version tag until the post-change gate and the environment-dependent acceptance evidence above are captured.

Once those checks pass, the branch is ready for release freezing.
