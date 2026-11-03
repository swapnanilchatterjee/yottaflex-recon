# AI Prompt & Collaboration History

**Candidate:** Swapnanil Chatterjee  
**Project:** Source-to-Target Data Pipeline & 4-Tier Reconciliation Engine  
**AI Assistant:** Antigravity CLI (Gemini 3.8 Flash)  
**Submission Requirement:** YottaFlex AI Candidate Project Submission Guidelines (Rule 03 — *Use LLMs Transparently*)

---

## Overview

This document records the prompt sequence and technical instructions issued during the incremental development of the data reconciliation tool. Development was driven phase-by-phase using structured prompt engineering, code reviews, precision adjustments, and manual validation.

---

### Prompt 0: Architecture & Domain Definition
- **Phase:** System Design & Domain Modeling
- **Prompt:**
  ```text
  Review the business requirements for the source-to-target reconciliation challenge:
  1. Business problem: Ingest source extracts, publish target datasets, and perform multi-level reconciliation isolating every mismatch.
  2. Constraints: Python 3.10+, pandas, numpy, pytest, standard library only. No external cloud or databases.
  3. Propose a two-entity domain that supports real foreign key relationships without bloat.
  4. Define the 4-tier reconciliation methodology and the core count equation.
  ```
- **Engineering Review & Validation:**
  - Selected e-commerce domain: `customers` (parent) and `orders` (child).
  - Formulated the count equation: `source_raw_rows = expected_target_rows + rejected_rows`.
  - Established the reject quarantine schema with physical source line tracking.

---

### Prompt 1: Project Scaffolding & Schemas
- **Phase:** Phase 1 & 2 — Scaffolding & Schema Definitions
- **Prompt:**
  ```text
  Scaffold the project layout for `yottaflex-recon`:
  - Create requirements.txt (pandas, numpy, pytest), pyproject.toml, .gitignore, and Makefile.
  - Implement src/recon/schemas.py defining:
    - Column specifications and regex rules: customer_id (^C\d{6}$), order_id (^O\d{8}$).
    - Target schemas: dim_customers, fact_orders.
    - Explicit lineage columns: source_file, run_id.
    - Constant reject codes: MALFORMED_ROW, MISSING_REQUIRED, INVALID_FORMAT, INVALID_TYPE, INVALID_VALUE, FUTURE_TIMESTAMP, INVALID_FK, DUPLICATE_SUPERSEDED.
  - Implement src/recon/runlog.py computing a deterministic run_id from a SHA-256 hash of all input file bytes + version.
  ```
- **Engineering Review & Validation:**
  - Verified `compute_run_id` produces identical digests for identical input bytes.
  - Defined `RECON_EXCLUDE_COLUMNS = {"run_id", "source_file"}` so operational metadata is excluded from data drift checks.

---

### Prompt 2: Resilient Ingestion
- **Phase:** Phase 3 — Ingestion & Malformed Row Quarantine
- **Prompt:**
  ```text
  Implement src/recon/ingest.py using Python's standard library `csv.reader`:
  - Read input files line-by-line while recording physical 1-based source_line_number.
  - Handle UTF-8 BOM encoding automatically.
  - Header check: raise SchemaError(SCHEMA_MISSING_COLUMNS) if mandatory columns are missing.
  - Drift policy: if extra unrecognized columns exist, log a warning and continue.
  - Ingestion resilience: if a ragged line has too few or too many fields, quarantine it as MALFORMED_ROW with its line number and raw text. Do not crash.
  - Write unit tests in tests/test_ingest.py.
  ```
- **Engineering Review & Validation:**
  - Confirmed that standard library `csv` avoids the hard C-level crash of `pd.read_csv` when encountering malformed lines.
  - Checked that header line is counted as Line 1 and data rows start from Line 2.

---

### Prompt 3: Validation, Deduplication & Referential Integrity
- **Phase:** Phase 4 — Data Validation & Quarantine
- **Prompt:**
  ```text
  Implement src/recon/validate.py:
  1. Constraint checks: regex patterns for keys, ISO-8601 timestamp parsing, amount decimal range [0.00, 1000000.00], allowed status set, allowed currency set, and reject future timestamps.
  2. Intersystem constraint: updated_at >= created_at for customers.
  3. Deduplication rule: for duplicate keys within a batch, retain the record with the maximum updated_at (tie-breaker: latest appearance in file). Route superseded records to rejects as DUPLICATE_SUPERSEDED.
  4. Referential integrity: validate orders against valid customers. Quarantine orphan orders as INVALID_FK.
  5. Enforce invariant: len(input) == len(valid) + len(rejects).
  - Write comprehensive tests in tests/test_validate.py.
  ```
- **Engineering Review & Validation:**
  - Hand-checked deduplication group sorting to verify that out-of-order files are correctly handled (max `updated_at` wins regardless of line position).
  - Confirmed row conservation invariant holds across all negative test cases.

---

### Prompt 4: Deterministic Transformation
- **Phase:** Phase 5 — Normalisation & Derived Fields
- **Prompt:**
  ```text
  Implement src/recon/transform.py as pure functions:
  - String cleaning: whitespace trimming, lowercase emails, uppercase country codes and currencies.
  - Timezone normalisation: convert all ISO-8601 timestamps (including offsets like +05:30) to canonical UTC ISO-8601 ending in 'Z'.
  - Derive UTC order_date (YYYY-MM-DD).
  - Monetary precision: use Decimal ROUND_HALF_UP to quantise amounts to 2 decimal places. Avoid float rounding drift.
  - Derive categorical amount_band: 'low' (< 100), 'medium' (100 to 999.99), 'high' (>= 1000).
  - Add tests in tests/test_transform.py covering boundary values (99.99, 100.00, 999.99, 1000.00).
  ```
- **Engineering Review & Validation:**
  - Verified boundary conditions for `amount_band` to ensure exact boundary inclusivity.
  - Confirmed financial amounts round properly (e.g. `10.005` $\rightarrow$ `10.01`).

---

### Prompt 5: Idempotent Target Publishing
- **Phase:** Phase 6 — Target Publishing & Idempotency
- **Prompt:**
  ```text
  Implement src/recon/publish.py:
  - Implement an atomic upsert on the primary key.
  - Enforce an updated_at stale guard: an incoming row only overwrites an existing analytical row if incoming.updated_at >= target.updated_at. If older, count as skipped_stale and preserve target.
  - Write targets atomically: write to a temporary file (tmp_publish_*.csv) in the target directory, then swap via os.replace.
  - Deterministic serialization: sort output by primary key before writing.
  - Return metrics: inserted, updated, unchanged, skipped_stale.
  - Add idempotency tests in tests/test_publish_idempotency.py (verifying identical SHA-256 hash on rerun).
  ```
- **Engineering Review & Validation:**
  - Simulated process crashes during file write; verified that the existing target remains uncorrupted.
  - Tested rerunning identical batches: verified `inserted=0, updated=0, unchanged=N`.

---

### Prompt 6: 4-Tier Reconciliation Engine
- **Phase:** Phase 7 — Reconciliation Engine & Report Serialization
- **Prompt:**
  ```text
  Implement src/recon/reconcile.py and src/recon/report.py:
  1. In-memory simulation: Run ingest, validate, and transform on raw sources to produce expected target and rejects.
  2. Tier 1: Evaluate the count equation (source_raw = expected_target + rejected). Flag any count discrepancy as unexplained_difference.
  3. Tier 2: Check key sets for missing_in_target, extra_in_target, and duplicate_in_target.
  4. Tier 3: Compute domain aggregates: row_count, sum(amount) with 0.005 tolerance, min/max, distinct customers.
  5. Tier 4: Vectorised field comparison: inner-join expected and actual on primary key; compare non-lineage payload columns.
  6. Output formatting: write reconciliation_report.json and isolate mismatches into separate CSVs (missing, extra, duplicates, field mismatches).
  - Exit codes: 0 for PASS, 1 for mismatches detected, 2 for fatal pipeline errors.
  ```
- **Engineering Review & Validation:**
  - Tested both clean runs (Mode A) and drifted runs (Mode B).
  - Ensured lineage columns (`run_id`, `source_file`) are never compared as data differences.

---

### Prompt 7: Seeded Synthetic Generator
- **Phase:** Phase 8 — Data Generator with Labelled Defects
- **Prompt:**
  ```text
  Implement src/recon/generator.py:
  - Generate source extracts, drifted target, and an expected findings answer key using numpy.random.default_rng(seed).
  - Support configurable volumes (50 to 100,000+ orders).
  - Inject 12 negative edge cases into source (negative amount, bad status, bad currency, orphan FK, future timestamp, ragged line, duplicate key).
  - Inject deliberate drift into target_drifted (deletions, extra rows, duplicate keys, mutated amounts, altered statuses).
  - Output expected_findings.json containing the ground-truth defect keys completely separate from input files.
  - Add tests in tests/test_generator_labels.py verifying the reconciliation engine catches 100% of injected defects.
  ```
- **Engineering Review & Validation:**
  - Verified determinism: running the generator twice with `seed=42` produces byte-identical files.
  - Verified that reconciliation on `target_drifted` reproduces all injected labels with zero false positives.

---

### Prompt 8: CLI, Manifests & Integration Tests
- **Phase:** Phase 9 & 10 — CLI, Telemetry & Integration
- **Prompt:**
  ```text
  Wire CLI commands in src/recon/cli.py and src/recon/__main__.py:
  - `python -m recon generate`
  - `python -m recon run`
  - `python -m recon reconcile`
  - Ensure every run records run_manifest.json (status, duration, input/output counts, rejects, failure reason) and appends to run_log.jsonl.
  - Implement full integration tests in tests/test_end_to_end.py and tests/test_edge_cases.py (zero-byte files, header-only empty batches, crash recovery).
  ```
- **Engineering Review & Validation:**
  - Executed end-to-end integration: `generate` $\rightarrow$ `run` $\rightarrow$ `reconcile`.
  - Confirmed `SUCCESS_EMPTY` behavior on header-only empty batches.

---

### Prompt 9: Performance Benchmarking & Optimization
- **Phase:** Phase 11 — Benchmark & Optimization Study
- **Prompt:**
  ```text
  Implement scripts/benchmark.py:
  - Run the full pipeline on 100,000 orders and 10,000 customers.
  - Record execution time across all 5 stages (Ingest, Validate, Transform, Publish, Reconcile).
  - Implement an optimization benchmark: compare naive row-by-row iteration (iterrows) against vectorised Pandas merge comparison.
  - Save output metrics to docs/evidence/benchmark.txt and format docs/PERFORMANCE.md.
  ```
- **Engineering Review & Validation:**
  - Measured live performance: total pipeline completed in 98.28s for 100,000 rows.
  - Empirically verified a **23.6x speedup** (0.104s vs 2.445s on 15,000 rows) using vectorised merge comparison over `iterrows`.

---

### Prompt 10: Documentation & QA Test Report
- **Phase:** Phase 12 — Documentation & Quality Assurance
- **Prompt:**
  ```text
  Draft comprehensive project documentation:
  - README.md: Architecture diagram, data model specifications, naming conventions, business rules, idempotency policies, and full QA Test Report.
  - docs/DATA_DICTIONARY.md: Complete entity schemas and derivation logic.
  - docs/DESIGN_NOTES.md: Trade-offs, assumptions, and scalability roadmap.
  - docs/AI_USAGE.md: Transparent disclosure of AI acceleration and human validation.
  - Ensure all markdown formatting is clean and reproducible.
  ```
- **Engineering Review & Validation:**
  - Verified all 35 tests pass cleanly in 1.27s.
  - Conducted mutation testing (corrupting a single target record to confirm non-zero exit code).
