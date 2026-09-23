# Independent feed processors

Each feed is a complete standalone Python process. There is no shared parser/enrichment/correlation module.

| Feed | Script | Input |
|---|---|---|
| SAIS IOR | SAIS_IOR.py | Raw AIS NMEA CSV |
| SAIS Global | SAIS_GLOBAL.py | Raw AIS NMEA CSV |
| MSIS | MSIS.py | Already-decoded CSV |
| LRIT | LRIT.py | Headerless LRIT CSV |
| VATMS East | VATMS_EAST.py | !WSVDM / compatible AIS |
| VATMS West | VATMS_WEST.py | $TMVTD plus AIS lines |
| NAIS | NAIS.py | !ABVDM / !ABVDO; $ABVSI ignored |

Edit only the top configuration section in each script:
- input type
- input folder
- TCP host/port
- output folder
- forwarding settings
- PostgreSQL connection

Pipeline inside each script:

    input
      -> feed-specific parsing/decoding
      -> source validation
      -> normalization
      -> feed-specific correlation
      -> WRS/PANS/NSC enrichment
      -> field-specific fallback
      -> MMSI persistent fallback
      -> XML validation
      -> XML output
      -> optional forwarding

Dynamic position/course/speed/heading/timestamps remain incoming/source values. Reference data fills missing reference/static/voyage values according to the frozen field-specific priority.

The Athena XTrack 41-field XML contract is emitted deterministically. Empty values are omitted.

## Test mode

Set RUN_ONCE=True and configure INPUT_FOLDER and OUTPUT_FOLDER.

Example:

    python3 Validation/Feeds/SAIS_IOR.py
