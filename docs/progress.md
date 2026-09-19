# Current build progress

Development branch: dev/validation-full-build

## Verified by CI
- Python 3.14 compile of the full Validation tree passes.
- Canonical 41-field specification count is exactly 41.
- XML FIELD_SPECS count is exactly 41 and matches the canonical list.
- XML contract test passes.
- Real-format SAIS, MSIS, LRIT, VATMS East, VATMS West and NAIS parser contract tests pass.
- Processor one-record/one-XML spooling test is included.
- Docker Compose syntax validation passes.
- Docker image build passes.

## Implemented in this branch
- One operational XML document per normalized source record.
- Exactly one XTrack per operational XML document.
- Deterministic canonical 41-field emission.
- XML validation before Forwarder spooling.
- Local downstream compatibility parsing before spool.
- Physical-line-aware AIS multipart handling: incomplete fragments emit only available identity facts; final fragment emits the complete assembled decode.
- Explicit malformed SAIS rejection reasons.
- TMVTD checksum validation.
- AIS navigation status normalization to the textual iTrackLib vocabulary.
- AIS vessel-type normalization to the textual iTrackLib vocabulary.
- Vigilance-to-identity mapping uses Friend / Neutral / Suspect textual values.
- Missing vessel names are not filled with fabricated UNKNOWN values.
- Parser reference database paths are configurable for Docker.
- Docker-safe Web Console service controller.
- Persistent Docker runtime reference DB paths.
- Continuous PANS importer in Compose.
- Offline image export/load scripts.
- CI compile, unit/source tests, Compose validation and Docker image build.

## Latest continuation work
- Expanded the validation gate to include the complete parser validation pipeline and added `scripts/run_validation_gate.sh` as the single-command full acceptance entrypoint.
- Reviewed the existing Router restart, fault-recovery, failure-scenario, TCP-routing, XML-contract, real-source and processor-spooling test coverage; these are now wired into the gate rather than being undocumented tests.

- Data Router Web Console now has a server-side filesystem folder browser for FILE sources.
- FILE source editing now provides selectable CSV/XML/JSON/TXT/NMEA/LOG/all-file patterns and persists the selected patterns to YAML.
- Docker Compose now shares the live `docker/` configuration directory between Parser, Router, Forwarder and Web Console so UI edits target the same configuration files used by the services.
- Web Console Docker configuration now points directly at the shared `/opt/validation/docker/sources.yaml`.
- Fixed malformed escaped-newline YAML in the Docker parser reference-database section.
- Added `scripts/validation_gate.py` for measurable compile, parser-contract, semantic, spoofing, Router integration/recovery and optional Docker gate execution.
- Added Router configuration-manager coverage for absolute production folders and file-type patterns.

## Still open before release
1. Full iTrackLib 41-field setter/type/unit/max-length audit must be completed and committed as the authoritative matrix.
2. Field-by-field PANS/NSC/WRS enrichment must be validated against representative real reference rows.
3. All source datasets need measured line-count -> XML-count -> accepted/rejected -> field-coverage reports.
4. VATMS/NAIS control-message semantics need explicit acceptance tests.
5. Restart/recovery and duplicate/retry tests must be run through the complete Docker stack.
6. End-to-end Router -> Parser -> Enrichment -> XML -> Forwarder acceptance remains outstanding.
7. Offline image export/load must be tested on the target Ubuntu environment.
8. No release tag/version should be created until these gates pass.
