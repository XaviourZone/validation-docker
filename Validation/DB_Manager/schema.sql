-- Validation PostgreSQL schema
CREATE TABLE IF NOT EXISTS source (
    source_id INTEGER PRIMARY KEY,
    source_name TEXT UNIQUE NOT NULL,
    source_label TEXT,
    input_type TEXT,
    receive_port INTEGER,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS field_mapping (
    mapping_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    input_field TEXT NOT NULL,
    target_field TEXT NOT NULL,
    transformation TEXT,
    required BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_order INTEGER,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(source_name,input_field,target_field)
);

CREATE TABLE IF NOT EXISTS unlocode (
    locode TEXT PRIMARY KEY,
    country_code TEXT,
    location_code TEXT,
    location_name TEXT,
    subdivision TEXT,
    function_code TEXT,
    status TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS destination_mapping (
    destination_key TEXT PRIMARY KEY,
    destination_name TEXT NOT NULL,
    locode TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reference_wrs_current (
    record_id BIGSERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    vessel_id TEXT,
    mmsi BIGINT,
    imo BIGINT,
    callsign TEXT,
    vessel_name TEXT,
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(dataset_name,natural_key)
);
CREATE INDEX IF NOT EXISTS idx_wrs_current_mmsi ON reference_wrs_current(mmsi);
CREATE INDEX IF NOT EXISTS idx_wrs_current_imo ON reference_wrs_current(imo);
CREATE INDEX IF NOT EXISTS idx_wrs_current_callsign ON reference_wrs_current(callsign);
CREATE INDEX IF NOT EXISTS idx_wrs_current_name ON reference_wrs_current(upper(vessel_name));
CREATE INDEX IF NOT EXISTS idx_wrs_current_vessel_id ON reference_wrs_current(vessel_id);

CREATE TABLE IF NOT EXISTS reference_wrs_history (
    history_id BIGSERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    version_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS reference_pans_current (
    record_id BIGSERIAL PRIMARY KEY,
    document_type TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    mmsi BIGINT,
    imo BIGINT,
    callsign TEXT,
    vessel_name TEXT,
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(document_type,natural_key)
);
CREATE INDEX IF NOT EXISTS idx_pans_current_mmsi ON reference_pans_current(mmsi);
CREATE INDEX IF NOT EXISTS idx_pans_current_imo ON reference_pans_current(imo);
CREATE INDEX IF NOT EXISTS idx_pans_current_callsign ON reference_pans_current(callsign);
CREATE INDEX IF NOT EXISTS idx_pans_current_name ON reference_pans_current(upper(vessel_name));

CREATE TABLE IF NOT EXISTS reference_pans_history (
    history_id BIGSERIAL PRIMARY KEY,
    document_type TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    version_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS reference_nsc_current (
    record_id BIGSERIAL PRIMARY KEY,
    natural_key TEXT NOT NULL UNIQUE,
    source_region TEXT,
    mmsi BIGINT,
    imo BIGINT,
    callsign TEXT,
    vessel_name TEXT,
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nsc_current_mmsi ON reference_nsc_current(mmsi);
CREATE INDEX IF NOT EXISTS idx_nsc_current_imo ON reference_nsc_current(imo);
CREATE INDEX IF NOT EXISTS idx_nsc_current_callsign ON reference_nsc_current(callsign);
CREATE INDEX IF NOT EXISTS idx_nsc_current_name ON reference_nsc_current(upper(vessel_name));
CREATE INDEX IF NOT EXISTS idx_nsc_current_region ON reference_nsc_current(source_region);

CREATE TABLE IF NOT EXISTS reference_nsc_history (
    history_id BIGSERIAL PRIMARY KEY,
    natural_key TEXT NOT NULL,
    version_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_region TEXT,
    source_file TEXT,
    source_hash TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS import_batch (
    batch_id BIGSERIAL PRIMARY KEY,
    source_system TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    files_discovered INTEGER NOT NULL DEFAULT 0,
    files_loaded INTEGER NOT NULL DEFAULT 0,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS import_file (
    file_id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT REFERENCES import_batch(batch_id),
    source_system TEXT NOT NULL,
    source_region TEXT,
    document_type TEXT,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash_sha256 TEXT NOT NULL,
    file_size_bytes BIGINT,
    target_table TEXT,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_import_file_hash ON import_file(file_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_import_file_status ON import_file(status);

CREATE TABLE IF NOT EXISTS mmsi_history (
    mmsi BIGINT PRIMARY KEY,
    values_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_tx_iso TEXT,
    last_source TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pans_pending (
    file_hash_sha256 TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
