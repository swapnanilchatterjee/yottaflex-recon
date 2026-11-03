# Performance Benchmark & Optimization Analysis

This document records the empirical performance benchmarks measured on the YottaFlex pipeline, comparing pipeline execution phases and analyzing the impact of vectorised dataset comparison.

---

## 1. Test Environment

- **Operating System:** Windows 11
- **CPU:** Intel / AMD x86_64 Architecture
- **Python Version:** 3.10.11
- **Libraries:** Pandas 2.3.0, NumPy 2.2.6
- **Dataset Volume:** 100,000 Order Records, 10,000 Customer Records
- **Evidence Log:** `docs/evidence/benchmark.txt`

---

## 2. End-to-End Pipeline Timing (100,000 Orders)

| Pipeline Phase | Measured Duration | Throughput (Rows/sec) | Key Operations |
| :--- | :--- | :--- | :--- |
| **Ingestion** | `0.793 s` | ~126,100 rows/s | Stdlib CSV parsing, line counting, malformed row quarantine |
| **Validation & Dedup** | `33.803 s` | ~2,950 rows/s | Regex checking, timestamp parsing, decimal validation, FK check, intra-batch max updated_at dedup |
| **Transformation** | `13.797 s` | ~7,250 rows/s | Case/whitespace normalisation, Decimal HALF_UP quantisation, UTC string formatting, amount banding |
| **Publishing** | `0.631 s` | ~158,400 rows/s | Stale guard verification, atomic temporary file write & `os.replace` |
| **Reconciliation** | `49.255 s` | ~2,030 rows/s | 4-tier check (counts, key differences, aggregate sums/extrema, vectorised field diff) |
| **Total Pipeline** | **98.280 s** | **~1,017 rows/s** | Full ingestion to verified reconciliation report |

---

## 3. Optimization Deep Dive: Vectorised Merge vs Naive Row Loop

During field-level reconciliation, every non-lineage attribute of matched business keys must be compared. 

### The Problem with the Naive Approach
A conventional naive approach iterates row-by-row using `for _, row in df.iterrows()`:
```python
# Naive row iteration (O(N) with heavy Python interpreter overhead)
for _, exp_row in exp_df.iterrows():
    act_row = act_dict.get(exp_row["order_id"])
    for col in compare_cols:
        if exp_row[col] != act_row[col]:
            mismatches.append(...)
```
Each iteration constructs a Pandas `Series` object and invokes dynamic hash-table lookups, yielding extreme Python interpreter overhead.

### The Vectorised Merge Optimization
Instead, we perform a vectorised inner-join on the primary key, followed by vectorised column mask operations implemented in NumPy/C:
```python
# Vectorised C-level comparison
merged = pd.merge(exp_df, act_df, on="order_id", suffixes=("_src", "_tgt"))
for col in compare_columns:
    mask = (merged[f"{col}_src"] != merged[f"{col}_tgt"])
    if mask.any():
        ...
```

### Empirical Results (Measured on 15,000 Row Sample)

| Approach | Measured Duration | Relative Speed |
| :--- | :--- | :--- |
| **Naive `iterrows` Loop** | `2.445 s` | Baseline (1.0x) |
| **Vectorised Pandas Merge** | `0.104 s` | **23.6x Faster** |

> **Conclusion:** The vectorised join approach achieves a **23.6x speedup** on field-level checks, reducing comparison overhead from seconds to milliseconds and enabling the pipeline to comfortably scale to hundreds of thousands of records in memory.
