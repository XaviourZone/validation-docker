# Validation Docker

Docker-targeted continuation of the Validation maritime/AIS processing project.

Target pipeline: INPUT → INGESTION → PARSING/DECODING → NORMALIZATION → VALIDATION → CORRELATION → REFERENCE ENRICHMENT → FUSION → FINAL DATA → XML GENERATION → DOWNSTREAM DELIVERY.

Development baseline only. No release/version is considered complete until the source audit, XML contract validation, tests, restartability checks, and offline Docker deployment checks pass.
