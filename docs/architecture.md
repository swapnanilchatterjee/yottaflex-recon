# System Architecture & Flow Design

The diagram below illustrates the end-to-end data lifecycle, from source extraction and resilient ingestion to idempotent publishing, quarantine routing, and 4-tier reconciliation.

---

## 1. Architectural Workflow Diagram

```mermaid
flowchart TD
    subgraph Ingestion_Layer [1. Ingestion Layer]
        A1[source/customers.csv] --> B1[ingest_csv<br/>stdlib csv.reader, line tracking]
        A2[source/orders.csv] --> B2[ingest_csv<br/>stdlib csv.reader, line tracking]
        B1 -->|Ragged / Bad Columns| Q[(rejects/quarantine)]
        B2 -->|Ragged / Bad Columns| Q
    end

    subgraph Validation_Layer [2. Validation & Deduplication]
        B1 --> C1[validate_customers<br/>Regex, Types, updated_at >= created_at]
        B2 --> C2[validate_orders<br/>Amounts, Currencies, Statuses, Future TS]
        C1 -->|Format / Constraint Violations| Q
        C2 -->|Format / Constraint Violations| Q
        C1 -->|Valid Customer IDs| FK[FK Referential Check]
        FK -->|Orphan Orders| Q
        C1 -->|Superseded Versions| Q
        C2 -->|Superseded Versions| Q
    end

    subgraph Transform_Layer [3. Transformation Layer]
        C1 --> D1[transform_customers<br/>Trim, Lower, UTC ISO-8601]
        C2 --> D2[transform_orders<br/>Decimal HALF_UP, Amount Band, UTC Dates]
    end

    subgraph Publishing_Layer [4. Idempotent Target Layer]
        D1 --> E1[publish_dataset<br/>Atomic replace, updated_at guard]
        D2 --> E2[publish_dataset<br/>Atomic replace, updated_at guard]
        E1 --> T1[(target/dim_customers.csv)]
        E2 --> T2[(target/fact_orders.csv)]
    end

    subgraph Reconciliation_Layer [5. 4-Tier Reconciliation Engine]
        A1 & A2 -.-> R[recon engine<br/>In-memory Pipeline Simulation]
        T1 & T2 --> R
        R --> R1[1. Row Count Equation]
        R --> R2[2. Business Key Sets]
        R --> R3[3. Domain Aggregates]
        R --> R4[4. Vectorised Field Diff]
        R1 & R2 & R3 & R4 --> REP[reconciliation_report.json]
        R1 & R2 & R3 & R4 --> MIS[(mismatches/*.csv)]
    end

    subgraph Telemetry [6. Observability & Audit]
        B1 & C1 & D1 & E1 & R --> MAN[run_manifest.json + run_log.jsonl]
    end
```

---

## 2. Component Responsibility Matrix

| Module | Core Function | Failure Mode / Handling |
| :--- | :--- | :--- |
| `recon.ingest` | Reads CSV line-by-line; attaches physical line numbers. | Quarantines malformed field-count rows as `MALFORMED_ROW`. Missing required header column fails run (`SCHEMA_MISSING_COLUMNS`). |
| `recon.validate` | Applies business rules, regex formats, and inter-entity FK checks. | Quarantines failing records with explicit reason code; supersedes older versions with `DUPLICATE_SUPERSEDED`. Invariant: `input == valid + rejects`. |
| `recon.transform` | Pure deterministic conversions: Decimal `ROUND_HALF_UP`, UTC dates, amount banding. | Deterministic sorting by PK ensuring reproducible output bytes. |
| `recon.publish` | Updates target datasets idempotently. | Guarded upsert: rows with older `updated_at` are skipped (`skipped_stale`). Writes to temp file then atomic `os.replace`. |
| `recon.reconcile` | Compares expected target vs actual target across 4 tiers. | Solves count equation; isolates missing, extra, duplicate, and mismatched fields into discrete CSVs. |
| `recon.runlog` | Computes content-hash `run_id`, logs structured events, records run manifest. | Non-zero exit code on failure, persists attempt number and failure reason. |
