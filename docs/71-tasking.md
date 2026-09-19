# Validation Docker — 71 Tasking Implementation Matrix

This is the implementation control document for the Docker-targeted Validation build. It decomposes the established project requirements into 71 executable engineering taskings. Status is updated only from repository evidence and test results.

Legend: ☐ pending  ☑ implemented  ◐ under audit  ✗ failed

## A. Baseline and architecture
1. ☑ Freeze the 41-tag XML master list and treat it as the canonical logical-field contract.
2. ☑ Audit every canonical XML tag against the actual iTrackLib parser implementation.
3. ☑ Record downstream type, unit, scale, conversion and setter behavior for every supported tag.
4. ☑ Separate facts, observations, proposals and assumptions in the mapping documentation.
5. ☑ Preserve raw, decoded, normalized, validated, correlated, enriched, fused and XML stages as distinct processing states.
6. ☑ Preserve source provenance end-to-end, including SAIS_IOR vs SAIS_GLOBAL and VATMS East vs West.
7. ☑ Keep the Router transport-only; no decoding, enrichment or XML generation in Router.
8. ☑ Keep source-specific parsing isolated behind the common parser boundary.
9. ☑ Keep database/reference access behind a single reference abstraction.
10. ☑ Keep output delivery behind the Forwarder spool/transport boundary.

## B. Source ingestion and parsing
11. ☑ Audit SAIS_IOR sample format and parser behavior.
12. ☑ Audit SAIS_GLOBAL sample format and parser behavior.
13. ☑ Audit SAIS IEC 61162 Tag Block timestamp extraction and NMEA checksum handling.
14. ☑ Audit AIS message types 1–27 and preserve supported raw message types without silent discard.
15. ☑ Design multipart AIS handling so every physical input line has deterministic processing semantics without fabricated vessel values.
16. ☑ Audit MSIS real CSV header/column mapping and one-row-per-record behavior.
17. ☑ Audit LRIT real 20-column headerless CSV mapping.
18. ☑ Audit LRIT empty/zero-byte file behavior.
19. ☑ Audit VATMS_EAST !WSVDM/!AIVDM parsing.
20. ☑ Audit VATMS_WEST $TMVTD parsing and units.
21. ☑ Audit NAIS !ABVDM/!ABVDO handling and $ABVSI treatment.
22. ☑ Preserve malformed-line rejection reasons and source/message/line context.
23. ☑ Make parser success/ACK semantics tolerate partial records while still reporting rejected records.
24. ☑ Verify no parser silently drops a non-empty input record without a reason.

## C. 41-field normalization
25. ☑ Build one canonical NormalizedRecord representation for all 41 fields.
26. ☑ Normalize latitude/longitude to radians for XML.
27. ☑ Normalize course/heading to radians for XML.
28. ☑ Normalize speed to metres/second for XML.
29. ☑ Normalize timestamps to epoch milliseconds where the downstream contract requires them.
30. ☑ Preserve source timestamp separately from receipt timestamp.
31. ☑ Preserve original transmitted MMSI in id.mmsi.
32. ☑ Populate corrected/reference MMSI only in foreign.track.number according to the established rule.
33. ☑ Populate sys.track.number from the original incoming AIS MMSI where applicable.
34. ☑ Normalize AIS navigation status consistently.
35. ☑ Normalize AIS type/cargo using actual source code and established decode logic.
36. ☑ Ensure dimension fields never derive unsupported bow/stern or port/starboard values.
37. ☑ Ensure kinematic.flag.3d is based only on actual source altitude/Z evidence.
38. ☑ Resolve destinations through the bundled offline UN/LOCODE dictionary without online calls.

## D. Reference enrichment and correlation
39. ☑ Perform one reference resolution per incoming record rather than one DB query per field.
40. ☑ Apply field-level fallback in PANS → NSC → WRS order when the incoming value is missing.
41. ☑ Keep supplied live values authoritative over reference values.
42. ☑ Verify PANS VESPRO mapping for name/callsign/beam/LOA/draft/GRT/type/IMO/MMSI.
43. ☑ Verify PANS CALINF mapping for origin/LPC/NPC/ETA/ETD/VCN.
44. ☑ Verify PANS BERMAN mapping for destination/LPC/NPC/ETA/ETD/drafts.
45. ☑ Verify WRS vessel, dimensions, vigilance, calling and AIS decode mappings against actual imported headers.
46. ☑ Inspect and verify actual NSC columns before finalizing NSC field mappings.
47. ☑ Implement IMO/MMSI/name identity correlation rules exactly as established.
48. ☑ Implement vigilance-to-identity boundaries: 299→Friend(1), 300→Neutral(3), 600→Neutral(3), 601→Suspect(4).
49. ☑ Implement track.active exactly at the established 3-hour boundary.
50. ☑ Generate provenance and point-wise remarks only from actual evidence.

## E. XML generation and downstream compatibility
51. ☑ Generate exactly one XTrack per XML document.
52. ☑ Ensure one physical source input line produces one output XML document, subject to explicit multipart semantics.
53. ☑ Never bundle unrelated records into one operational XML document.
54. ☑ Emit fields in deterministic canonical order.
55. ☑ Serialize each field using its downstream-required iv/sv/bv/qv/tv representation.
56. ☑ Enforce XML-safe string escaping and sanitation.
57. ☑ Validate every XML document as well-formed XML with exactly one XTrack.
58. ☑ Round-trip every generated XML through a local downstream compatibility parser.
59. ☑ Compare compatibility behavior against the authoritative iTrackLib source audit.
60. ☑ Produce a per-record field coverage report showing present/absent canonical tags.

## F. Router, state, reliability and Forwarder
61. ☑ Verify all seven operational source paths and five parser endpoints.
62. ◐ Preserve stable-file detection, duplicate hashing, persistent state and restart recovery.
63. ☑ Preserve bounded queue/backpressure and independent source isolation.
64. ☑ Verify ACK message_id matching, NACK handling and retries.
65. ☑ Verify TCP framing/reconnect behavior and partial-read handling.
66. ☑ Verify Forwarder persistent delivery state, retry, archive and failure spool behavior.

## G. Docker and offline deployment
67. ☑ Build a common offline-capable Validation runtime image containing finalized services and dependencies.
68. ☑ Add Compose definitions with persistent config/data/state/log volumes and healthchecks.
69. ☑ Add offline image save/load and deployment scripts; do not require Internet at deployment time.
70. ☑ Add complete source, unit, integration, XML, restart and Docker smoke-test entry points with measurable pass/fail output.
71. ☐ Perform final end-to-end acceptance: source input → Router → Parser → normalization/validation/correlation/enrichment → XML → Forwarder, then freeze release only after all mandatory checks pass.

## Release gate
No production/version release is considered complete until the unresolved audit items are either implemented with evidence or explicitly documented as blocked by missing authoritative source information.
