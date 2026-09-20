# MMSI Last-Known Reference Fallback

## Purpose

The Data Parser now maintains one persistent cumulative reference record for every
valid MMSI seen by the parser.

This is not a second reference database. WRS, PANS and NSC remain authoritative
reference sources. The MMSI record is a final fallback used only when:

1. the current transaction does not contain a value;
2. PANS does not provide it;
3. NSC does not provide it; and
4. WRS does not provide it.

## Storage

The existing TrackStateDB SQLite file is extended with the mmsi_reference table.

| Column | Meaning |
|---|---|
| mmsi | Unique MMSI, primary key |
| values_json | Cumulative last-known non-empty reference values |
| last_tx_iso | Last transaction timestamp seen for the MMSI |
| last_source | Source of the latest transaction |
| updated_at | Reference-row update time |

The row is updated on every transaction for a valid MMSI. A blank current value
never erases a previously known value.

## Fallback order

For each canonical field:

CURRENT INCOMING -> PANS -> NSC -> WRS -> MMSI_HISTORY

AIS dynamic position, course, speed, heading and timestamps are not copied from
older transactions.

The stored reference can retain identity, dimensions, type/description, tonnage,
callsign, IMO, MMSI-related fields and the current voyage/reference fields so that
a missing value can be recovered from an earlier transaction.

## Provenance

Acceptance output records:

INCOMING, PANS, NSC, WRS, MMSI_HISTORY, DERIVED, or NONE.

When a value is recovered from the persistent per-MMSI store, the field is marked
MMSI_HISTORY and the recovered logical field is listed in mmsi_history_recovered.

## Efficiency

ReferenceDB also uses a bounded 8192-entry in-process LRU cache keyed by the
incoming identity tuple. This avoids repeating the same multi-query WRS/PANS/NSC
resolution for repeated transmissions while preserving the existing SQLite
databases and their schema.

The cache is read-only and bounded; no new database indexes are required.

## Operational database

The production parser state file remains:

Validation/state/track_state.db

The acceptance runner creates an isolated temporary TrackStateDB, so acceptance
tests do not modify the production state database.

## Important semantic boundary

The MMSI history is a fallback, not a replacement for current AIS or reference
data. If WRS/PANS/NSC supplies a current value, that value wins over an older MMSI
value.

Voyage fields may naturally become stale; they are retained only because the
explicit requirement is to recover a missing field from the vessel's earlier
MMSI transaction when all reference databases lack it.
