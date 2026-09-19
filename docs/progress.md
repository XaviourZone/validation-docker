# Current build progress

Development branch: dev/validation-full-build

## Verified evidence

- The latest pre-hardening physical validation gate passed **6/6**:
  - Python compile
  - Parser contract/source/semantic/spoofing tests
  - Full pipeline acceptance
  - Router integration/recovery
  - Docker Compose syntax
  - Docker image build
- The full pipeline acceptance physically exercised SAIS_IOR file input → Router → real Parser endpoint → parser pipeline → XML → Forwarder pending spool → filesystem delivery.
- The Router restart/recovery integration suite physically covered duplicate suppression, interrupted delivery recovery, downstream retry and TCP reconnect behavior.
- Docker Compose syntax and the common runtime image build pass.
- Operational WRS/PANS/NSC databases are absent from the clean repository; semantic testing uses a deterministic NSC fallback fixture where required. This verifies pipeline mechanics, not production reference-data coverage.

## Implemented in this branch

- One operational XML document per normalized source record.
- Exactly one XTrack per operational XML document.
- Deterministic canonical 41-field emission.
- XML validation before Forwarder spooling.
- Local downstream compatibility parsing before spool.
- Physical-line-aware AIS multipart handling.
- Explicit malformed SAIS rejection reasons.
- TMVTD checksum validation.
- AIS navigation-status and vessel-type normalization to the established iTrackLib vocabulary.
- Vigilance-to-identity mapping with the established boundary values.
- Missing vessel names are not filled with fabricated UNKNOWN values.
- Parser reference database paths are configurable for Docker.
- Docker-safe Web Console service controller.
- Persistent Docker runtime reference DB paths.
- Continuous PANS importer in Compose.
- Data Router Web Console server-side filesystem folder browser.
- FILE source CSV/XML/JSON/TXT/NMEA/LOG/all-file pattern selection persisted to YAML.
- Shared live Docker configuration volume between Parser, Router, Forwarder and Web Console.
- Measurable validation gate and single-command gate runner.
- Router stable-file detection, content hashing, persistent state and restart recovery.
- Additional Task 62 focused lifecycle tests covering stability, persistent duplicate suppression and queue-rejection recovery.
- Explicit VATMS/NAIS control-message acceptance tests.
- Offline Docker image export/load scripts.
- Offline Docker image save/load round-trip validation is now part of the Docker gate.

## Final hardening changes

- File-source in-memory in-flight tracking is now strictly a concurrent-submission guard and is always released.
- Persistent SQLite state remains the authoritative duplicate/lifecycle record.
- Queue rejection or file-read failure returns the file to DISCOVERED with the error retained, allowing a later scan to retry rather than permanently suppressing the file.
- Validation gate now includes Task 62 lifecycle tests, explicit control-message tests and offline image save/load.

## Release evidence still required

1. **Post-change full gate run** on the prepared/offline Ubuntu environment. The previous 6/6 result predates the final hardening changes.
2. **Production reference-data evidence:** representative real WRS/PANS/NSC databases must be supplied/mounted to validate field-level enrichment against authoritative rows. The repository does not contain those operational databases.
3. **Production dataset measurement:** actual SAIS_IOR, SAIS_GLOBAL, MSIS, LRIT, VATMS and NAIS datasets must be present to produce measured file/line → parsed/rejected → XML → field-coverage reports. No production counts are invented.
4. **Complete Docker-stack restart/recovery run:** the existing Router integration tests are physical service-boundary tests, while the release evidence should also run restart/recovery through the deployed Compose stack.
5. **Authoritative iTrackLib max-length audit:** current XML field specs contain logical type/unit information, but a trustworthy maximum-length value must come from the authoritative iTrackLib source/contract. No max lengths are guessed.
6. Do not create a release/version tag until the above evidence is captured.

## Current status

Implementation work for the repository is complete through the final hardening pass. The remaining items are **environment-dependent acceptance evidence**, not silently assumed production results.
