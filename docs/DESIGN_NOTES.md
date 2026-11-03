# Design Notes, Assumptions & Trade-offs

This document details the architectural decisions, trade-offs, operational failure modes, and scalability considerations chosen for the YottaFlex Source-to-Target Reconciliation Engine.

---

## 1. Core Engineering Decisions & Trade-offs

### 1.1 In-Memory vs External Database
- **Decision:** Pure Python 3.10+ and `pandas` without external databases (PostgreSQL/DuckDB/SQLite).
- **Why:** Delivers an ultra-portable, self-contained vertical slice requiring zero database servers, credential setup, network sockets, or permissions. It runs deterministically across local developer machines and CI runners.
- **Trade-off:** Constrained by available RAM. At 100,000–500,000 records, in-memory operations execute comfortably in seconds. For >10,000,000 records, the architecture would transition to DuckDB or PySpark.

### 1.2 Two-Stage CSV Ingestion (Standard Library `csv` -> `DataFrame`)
- **Decision:** Ingest raw CSV rows line-by-line using Python standard library `csv.reader` before constructing Pandas DataFrames.
- **Why:** `pandas.read_csv` throws parser errors when ragged rows (wrong field count) occur, crashing the entire load. The stdlib reader captures raw line numbers and routes malformed rows directly to the quarantine file (`MALFORMED_ROW`), while valid rows continue unhindered.
- **Trade-off:** Parsing line-by-line has higher CPU overhead than compiled C-readers, but is essential for line-level reject isolation.

### 1.3 Deduplication & Late-Arriving Data Policy
- **Decision:** Intra-batch deduplication keeps the record with the maximum `updated_at` (tie-breaker: latest appearance in file). Superseded versions are preserved in quarantine as `DUPLICATE_SUPERSEDED`.
- **Decision:** Inter-batch publishing applies an **`updated_at` guard** (`incoming.updated_at >= target.updated_at`). Incoming rows with older version timestamps are counted as `skipped_stale` and prevented from clobbering newer data.
- **Trade-off:** Assumes `updated_at` timestamps are generated accurately by source systems.

### 1.4 Financial Rounding & Comparison Tolerance
- **Decision:** Amounts are quantised using `decimal.Decimal` with `ROUND_HALF_UP` to exactly two decimal places.
- **Decision:** Reconciliation allows a configurable tolerance (`amount_tolerance = 0.005`) when checking sums, aggregates, and field differences.
- **Why:** Binary floating-point arithmetic (IEEE 754) introduces infinitesimal rounding errors (`0.1 + 0.2 != 0.3`). A `0.005` tolerance eliminates false positive floating-point noise without masking real monetary errors (which are minimum 1 cent / `0.01`).

### 1.5 Atomic File Publishing
- **Decision:** Targets are written to a temporary sibling file in the same directory and renamed into place using `os.replace`.
- **Why:** Ensures POSIX/Windows atomic file swapping. If a power failure or pipeline crash occurs during write, the destination file remains uncorrupted at its last verified valid state.

---

## 2. Assumptions & Boundary Rules

1. **Header Order:** Columns may arrive in any header order. Ingestion resolves columns by header name rather than position.
2. **Schema Drift Policy:**
   - Missing required column -> Hard failure (`SCHEMA_MISSING_COLUMNS`, exit code 2).
   - Unrecognized / extra column -> Warning logged, extra columns dropped; known pipeline columns proceed normally.
3. **Empty Batches:**
   - Zero-byte file -> Pipeline error (`EMPTY_FILE_NO_HEADER`, exit code 2).
   - Valid header with zero data rows -> Valid empty batch (`SUCCESS_EMPTY`, exit code 0).
4. **Timezones:** Naive timestamps are interpreted as UTC; timestamps with offsets are parsed and normalised to UTC ISO-8601 `Z` format.
5. **Determinism:** Given identical input file bytes and pipeline version, `run_id` is identical (`run_<sha256[:12]>`).

---

## 3. Scalability & Next Steps for Production (10M+ Rows)

If scaling this pipeline to millions of daily records:
1. **Engine Evolution:** Replace pandas merge with **DuckDB** or **PySpark** using streaming or partitioned parquet files.
2. **Hash-Based Chunk Diffing:** Compute MD5/XXHash on non-lineage fields per row. Compare hash sets first (order of magnitude faster than multi-column value joins); drill down into field-level inspection only for rows whose hashes differ.
3. **Partitioned Storage:** Partition target tables by `order_date` (`target/fact_orders/order_date=YYYY-MM-DD/*.parquet`), enabling partitioned idempotent overwrites without rewriting full historical extracts.
4. **Orchestration & Alerting:** Wrap in Apache Airflow or Prefect with Slack/PagerDuty webhooks triggered on non-zero reconciliation exit codes (`exit code 1`).
