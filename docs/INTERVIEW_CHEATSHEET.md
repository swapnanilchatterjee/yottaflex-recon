# Interview Cheatsheet & Rapid Review

A quick-reference study guide summarizing the architecture, pitch, decisions, and common interviewer questions.

---

## 1. The 90-Second Solution Pitch

> "I built a production-grade source-to-target reconciliation tool and ingestion pipeline in Python and pandas. It ingests CSV extracts for customers and orders, validates them, quarantines bad rows with the reason and source line number, transforms deterministically, and publishes idempotently. The reconciliation engine compares source and target on four levels: row counts, business keys, aggregates, and field-level values. It writes a machine-readable JSON report and isolates every mismatched record into its own CSV.
>
> Two core ideas drive the design:
> 1. **The Count Equation:** Raw source rows must equal target rows plus rejected rows (`source_raw = expected_target + rejected`). Every difference is either fully explained by quarantined rejects or flagged as an unexplained count gap.
> 2. **Safe Reruns & Idempotency:** Run IDs are computed from a SHA-256 hash of the input bytes. Publishing uses an atomic file replacement guarded by `updated_at`, ensuring a second run inserts 0 rows and stale late data cannot clobber newer analytical data.
>
> I tested the pipeline against a seeded generator injecting labelled defects, proved that the reconciliation engine catches 100% of injected defects without false positives, and benchmarked 100k records—optimizing field comparison from an `iterrows` loop to a vectorised merge for a 23.6x speedup."

---

## 2. Key Architectural Decisions (What / Why / Trade-off)

| Decision | Why | Trade-off / Alternative |
| :--- | :--- | :--- |
| **Python + Pandas (No DB)** | Zero setup, fully portable, inspectable CSVs | Memory bound; for >10M rows use DuckDB/PySpark |
| **Two-Stage Ingest (stdlib csv -> df)** | Captures physical line numbers; isolates malformed rows without crashing | Slower than compiled C readers, but resilient |
| **Quarantine Path (Never silent drop)** | Data traceability is a core engineering requirement | Increases output volume |
| **Latest `updated_at` Wins** | Deterministic dedup; handles out-of-order streams | Assumes source timestamp integrity |
| **`updated_at` Guard on Upsert** | Prevents late-arriving stale data from overwriting newer target state | Requires version timestamps |
| **Deterministic `run_id`** | Content-hash of input bytes ensures reproducibility | Config change requires version bump |
| **Atomic File Replace** | Eliminates corrupted/half-written target files on crash | Rewrites full file at this scale |
| **Vectorised Merge Comparison** | Evaluates matched keys in C/NumPy (23.6x speedup) | Uses more memory during comparison |
| **Decimal HALF_UP for Money** | Eliminates floating-point penny rounding errors | Slight CPU overhead vs native float |
| **Tolerance 0.005 on Floats** | Absorbs precision noise without masking real cent errors | Configurable via CLI |

---

## 3. High-Frequency Interview Questions

1. **Why isn't row count matching enough?**
   *Answer:* Two flaws can cancel out: one missing row and one extra row give identical counts. Furthermore, counts cannot detect corrupted field values, currency drift, or duplicate primary keys.
2. **How do you make reruns safe?**
   *Answer:* The publisher performs an upsert matched on the business key with an `updated_at` guard, output is sorted deterministically by PK, and file writes use atomic replacement. Rerunning identical input produces `inserted=0, updated=0, unchanged=N` and an identical file hash.
3. **What if the pipeline crashes midway through a write?**
   *Answer:* Publishing writes to a temporary sibling file (`tmp_publish_*.csv`) and replaces the destination via `os.replace`. If a crash occurs, the original target file remains untouched at its last valid state.
4. **How do you handle late-arriving data?**
   *Answer:* Late records with an older `updated_at_utc` than the existing target record are detected by the stale guard and recorded as `skipped_stale` without overwriting the newer state.
5. **How did you handle financial amounts?**
   *Answer:* Ingested as raw strings, validated within range `[0.00, 1000000.00]`, and quantised using `decimal.Decimal` with `ROUND_HALF_UP` to 2 decimal places. A tolerance of `0.005` is applied during reconciliation to avoid floating-point false alarms.
6. **How would you scale this to 100 million rows?**
   *Answer:* 
   1. Shift from Pandas to DuckDB or PySpark.
   2. Partition target data by `order_date` (`fact_orders/order_date=YYYY-MM-DD/*.parquet`).
   3. Compute row hashes (MD5 or XXHash) on non-lineage fields: compare hash sets first; join column-level values only on hash mismatches.
