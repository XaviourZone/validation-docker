# Source audit baseline

This document records observations from the real sample files in the old Validation repository. It is not a substitute for the final acceptance run.

| Source | Sample evidence | Current parser | Important observations | Current status |
|---|---|---|---|---|
| SAIS_IOR | Validation/SAMPLE_DATA/SAIS/SAIS_IOR/EarthIOR_2026-06-25-14-21-28.csv | SAISParser | IEC 61162 tag blocks; !AIVDM; both single and 2-fragment messages occur; tag block contains c: epoch seconds. | Under audit |
| SAIS_GLOBAL | Validation/SAMPLE_DATA/SAIS/SAIS_GLOBAL/EarthGLOBAL_2026-06-25-14-21-39.csv | SAISParser | Same NMEA family; sample contains unusually short payloads that must be rejected with explicit reasons rather than silently discarded. | Under audit |
| MSIS | Validation/SAMPLE_DATA/MSIS/nc3in_20260601_130155.csv | MSISParser | Header is mmsi,latitude,longitude,sog,cog,true_heading,rate_of_turn,navigatetion_status,updated,source_name,classb_flag,ship_name,imo,callsign,length,width,draught,destination,type_and_cargo,eta. | Mapping verified against sample |
| LRIT | Validation/SAMPLE_DATA/LRIT/LRIT_03062026_093001.csv | LRITParser | Headerless 20-column rows; positions and timestamp present; many kinematic/static columns are None; vessel type/name/IMO occur. | Mapping verified against sample |
| VATMS_EAST | Validation/SAMPLE_DATA/VATMS/VATMS_EAST/vatms_east.txt | VATMSParser -> SAIS decoder | !WSVDM; both single and multipart AIS sentences occur. | Under audit |
| VATMS_WEST | Validation/SAMPLE_DATA/VATMS/VATMS_WEST/vatms_west.txt | VATMSParser | $TMVTD; both tracked (T) and dropped (D) target records occur; sample includes vessel alias, position, course, speed, type, callsign, dimensions, MMSI/IMO on richer rows. | Under audit |
| NAIS | Validation/SAMPLE_DATA/NAIS/Nais.txt | NAISParser -> SAIS decoder | !ABVDM / !ABVDO vessel messages plus $ABVSI station/status messages; multipart ABVDM occurs. $ABVSI is not a vessel track record. | Under audit |

## Physical-line XML rule

For vessel-bearing input records, the parser/processor is being changed toward:

physical source line -> one source record -> one normalized record -> one XML document -> one XTrack.

For multipart AIS, an incomplete fragment emits only the facts actually available from that fragment/cache; the final fragment emits the fully assembled AIS decode. No missing vessel values are fabricated.

Non-vessel/control records are treated separately:
- $ABVSI is station/status information, not a vessel track.
- VATMS $TMVTD ... D is a target-drop control record and currently has no sufficient canonical vessel identity for a meaningful 41-field vessel XTrack.
- Empty LRIT files are valid no-data polls.

## Sample-derived MSIS mapping

The real MSIS header is used rather than generic column guesses:

- mmsi -> id.mmsi
- latitude / longitude -> kinematic position
- sog -> speed in knots before normalization to m/s
- cog -> true course before normalization to radians
- true_heading -> heading before normalization to radians
- rate_of_turn -> internal ROT
- navigatetion_status -> AIS navigation status
- updated -> source timestamp
- ship_name -> vessel name
- imo -> IMO
- callsign -> callsign
- length, width, draught -> dimensions
- destination -> voyage destination
- type_and_cargo -> AIS type/cargo code
- eta -> voyage ETA

The current implementation should not silently rename the misspelled real column navigatetion_status; it intentionally supports that exact sample spelling.

## Sample-derived LRIT mapping

The current headerless mapping is based on the actual 20-column sample:

0 MMSI, 1 latitude, 2 longitude, 3 SOG, 4 COG, 5 heading, 7 navigation status, 8 timestamp, 11 vessel name, 12 IMO, 13 callsign, 14 length, 15 width, 16 draught, 17 destination, 18 vessel type, 19 ETA.

The final acceptance test must verify this against a representative set of LRIT files, including empty files and malformed rows.

## Measured sample inventory

The representative files in the established sample repository contain the following non-empty physical-line counts:

| Source | File | Non-empty lines | Observed special records |
|---|---|---:|---|
| SAIS_IOR | EarthIOR_2026-06-25-14-21-28.csv | 10,000 | 815 multipart AIS fragment lines |
| SAIS_GLOBAL | EarthGLOBAL_2026-06-25-14-21-39.csv | 10,000 | 278 multipart AIS fragment lines |
| MSIS | nc3in_20260601_130155.csv | 251 | 1 header + 250 data rows |
| LRIT | LRIT_03062026_093001.csv | 297 | Headerless 20-column rows |
| VATMS_EAST | vatms_east.txt | 372 | 290 multipart !WSVDM fragment lines |
| VATMS_WEST | vatms_west.txt | 2,393 | 870 target-drop D records |
| NAIS | Nais.txt | 1,598 | 655 $ABVSI status/control records; 458 multipart AIS fragment lines |

These counts are sample inventory measurements only. They are not yet the final parser-record/XML-output acceptance counts.
