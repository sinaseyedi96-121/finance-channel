"""Ingestion sources, one module per source. Each exposes a `fetch(...)` that
returns plain dicts ready for staging/dedup. Network failures are caught inside
each module so one dead source never takes down the whole run."""
