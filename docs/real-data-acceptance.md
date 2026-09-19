# Real-Data Acceptance

The repository-side 12/12 validation gate is complete. This runner provides the next
single-command acceptance step against the supplied sample/operational data tree.

## Run

From the repository root:

```bash
python3 scripts/real_data_acceptance.py --sample-root "/path/to/Sample data"
```

For the supplied package, the directory passed to `--sample-root` must contain:

- `WRS/Datasets`
- `WRS/Decode Files`
- `PANS`
- `NSC EAST and WEST`
- `SAIS_IOR`
- `SAIS_GLOBAL`
- `MSIS`
- `LRIT`
- `VATMS_EAST`
- `VATMS_WEST`
- `NAIS`

The command creates isolated reference databases and temporary state databases,
then runs the actual project `ReferenceDB` and `PipelineProcessor`. It writes:

- `runtime/real-data-acceptance/production_measurement.json`
- `runtime/real-data-acceptance/production_measurement.md`
- generated XML under `runtime/real-data-acceptance/xml/`

No source data or generated operational database is committed to Git.

## Acceptance chain

```
WRS/PANS/NSC source data
        ↓
SQLite reference databases
        ↓
ReferenceDB lookup
        ↓
PANS → NSC → WRS field enrichment
        ↓
SAIS / MSIS / LRIT / VATMS / NAIS
        ↓
PipelineProcessor
        ↓
41-field XML contract
        ↓
XML validity + field coverage
        ↓
records/sec + rejected records + XML count
```

## Operational production run

For final operational acceptance, point the same command at the authoritative
production input/reference export tree. The result is then the evidence to attach
to release readiness.

The project does not label sample-built databases as production databases.
