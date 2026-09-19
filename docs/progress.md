# Current build progress

Development branch: dev/validation-full-build

## Verified evidence

- The latest post-hardening physical validation gate passed **12/12** in GitHub Actions run **94** (job **105874005822**) on this branch.
- The gate covered:
  - Python compile
  - Parser contract/source/semantic/spoofing/control-message tests
  - Reference DB importer tests for WRS/PANS/NSC
  - Web Console folder/file-pattern configuration tests
  - XML field-coverage tests
  - Full SAIS_IOR file → Router → real Parser endpoint → pipeline → XML → Forwarder acceptance
  - Router integration/recovery and Task 62 lifecycle tests
  - Docker Compose syntax and common image build
  - Offline Docker image save/load round trip
  - Deployed Compose Parser/Router/Forwarder/Web restart/recovery
  - Release documentation consistency
- The deployed Compose restart test physically started Parser, Router, Forwarder and Web, verified their HTTP endpoints, restarted all four services, re-verified readiness, and cleaned up the stack.
- Operational WRS/PANS/NSC databases are absent from the clean repository. The importer tests use isolated temporary reference databases, while semantic tests use the deterministic NSC fixture where required. This verifies repository mechanics, not production reference-data coverage.

## Implemented in this branch

- Reference DB importers for WRS, PANS and NSC with staging/continuous-import behavior and import tracking.
- Field-level PANS → NSC → WRS fallback with live incoming values authoritative.
- Real-sample test structure for SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS East/West and NAIS.
- Web Console filesystem folder selection and persisted file-type pattern configuration.
- Router → Parser → Forwarder end-to-end acceptance and persistent lifecycle/recovery.
- Docker Compose restart/recovery and offline image save/load evidence.
- Canonical 41-field XML generation plus per-record field-coverage reporting/test coverage.
- Release documentation consistency checks.

## Release evidence still required

1. **Authoritative production reference-data evidence:** mount representative real WRS/PANS/NSC databases and verify actual rows/field enrichment. The repository does not contain those operational databases.
2. **Production dataset measurement:** run the actual SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS and NAIS datasets to produce measured file/line → parsed/rejected → XML → field-coverage reports.
3. **Authoritative iTrackLib max-length audit:** exact maximum string lengths still require the authoritative iTrackLib source/contract; no maximum lengths are guessed.
4. **Target-host deployment smoke test:** the repository-side Compose restart/recovery test has passed, but the target offline host should still run the stack once with its real mounted reference/data directories.
5. Do not create a release/version tag until the environment-dependent evidence above is captured.


## Real-data acceptance runner

The repository now includes `scripts/real_data_acceptance.py`, which builds isolated WRS/PANS/NSC databases from a supplied data tree, runs the actual reference lookup and `PipelineProcessor` against SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS_EAST, VATMS_WEST and NAIS, and produces XML field coverage plus throughput/rejection measurements. See `docs/real-data-acceptance.md`. This keeps operational data out of Git while making the final acceptance reproducible.
