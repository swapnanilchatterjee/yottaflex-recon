# Data Dictionary & Schema Specifications

This document outlines the entity specifications, grain, business keys, nullability constraints, validation rules, and schema evolutions across the source and published target data layers.

---

## 1. Source Entity Schemas (Raw CSV Extracts)

All source CSV records are initially ingested strictly as raw strings using the Python standard library `csv` module to preserve source line numbers and prevent implicit lossy type coercion.

### 1.1 `customers.csv`
- **Grain:** One record per customer account.
- **Primary / Business Key:** `customer_id`

| Column | Type | Nullable | Validation Rule | Target Mapping |
| :--- | :--- | :--- | :--- | :--- |
| `customer_id` | String | No | Exact regex `^C\d{6}$` (e.g. `C000001`) | `dim_customers.customer_id` |
| `customer_name` | String | No | Must be non-empty after string trimming | `dim_customers.customer_name` |
| `email` | String | Yes | Lowercased in target; blank/null permitted | `dim_customers.email` |
| `country_code` | String | No | Exactly 2 alphabetic characters (`^[A-Za-z]{2}$`) | `dim_customers.country_code` (uppercased) |
| `created_at` | Timestamp | No | ISO-8601 UTC or offset; must parse cleanly | `dim_customers.created_at_utc` |
| `updated_at` | Timestamp | No | ISO-8601 timestamp; must satisfy `updated_at >= created_at` | `dim_customers.updated_at_utc` |

### 1.2 `orders.csv`
- **Grain:** One record per customer order event / version.
- **Primary / Business Key:** `order_id`

| Column | Type | Nullable | Validation Rule | Target Mapping |
| :--- | :--- | :--- | :--- | :--- |
| `order_id` | String | No | Exact regex `^O\d{8}$` (e.g. `O00000001`) | `fact_orders.order_id` |
| `customer_id` | String | No | Foreign Key to valid, non-quarantined `customers` | `fact_orders.customer_id` |
| `order_ts` | Timestamp | No | ISO-8601 timestamp; cannot be in the future relative to run execution | `fact_orders.order_ts_utc` |
| `status` | String | No | Case-insensitive membership in: `created`, `paid`, `shipped`, `delivered`, `cancelled`, `refunded` | `fact_orders.status` (lowercased) |
| `amount` | Decimal | No | Valid numeric in range `[0.00, 1000000.00]` | `fact_orders.amount` (quantised to 2 dp) |
| `currency` | String | No | Case-insensitive membership in: `USD`, `EUR`, `INR`, `GBP` | `fact_orders.currency` (uppercased) |
| `updated_at` | Timestamp | No | ISO-8601 timestamp used for deduplication & stale guard | `fact_orders.updated_at_utc` |

---

## 2. Target Entity Schemas (Published Clean Datasets)

Published target CSVs represent the current, deterministic analytical layer. Lineage metadata is appended to trace the origin run and file.

### 2.1 `dim_customers.csv`
- **Primary Key:** `customer_id` (Unique, non-null)
- **Ordering:** Sorted ascending by `customer_id`

| Target Column | Physical Type | Description & Derivation Logic |
| :--- | :--- | :--- |
| `customer_id` | String | Formatted customer identifier (e.g. `C000001`). |
| `customer_name`| String | Whitespace-trimmed customer name. |
| `email` | String | Lowercased email address or empty string if null. |
| `country_code` | String | ISO 2-letter country code, normalised to uppercase. |
| `created_at_utc` | String (ISO-8601)| Creation timestamp converted to UTC and formatted as `YYYY-MM-DDTHH:MM:SSZ`. |
| `updated_at_utc` | String (ISO-8601)| Latest update timestamp in UTC (`YYYY-MM-DDTHH:MM:SSZ`). |
| `source_file` | String | Lineage: input file basename (`customers.csv`). |
| `run_id` | String | Lineage: deterministic execution run identifier (`run_<sha256[:12]>`). |

### 2.2 `fact_orders.csv`
- **Primary Key:** `order_id` (Unique, non-null)
- **Foreign Key:** `customer_id` references `dim_customers.customer_id`
- **Ordering:** Sorted ascending by `order_id`

| Target Column | Physical Type | Description & Derivation Logic |
| :--- | :--- | :--- |
| `order_id` | String | Formatted order identifier (e.g. `O00000001`). |
| `customer_id` | String | Validated foreign key referencing `dim_customers`. |
| `order_ts_utc` | String (ISO-8601)| Order placement timestamp converted to UTC (`YYYY-MM-DDTHH:MM:SSZ`). |
| `order_date` | String (ISO-8601)| Derived calendar date in UTC (`YYYY-MM-DD`). |
| `status` | String | Canonical lowercase order lifecycle status. |
| `amount` | String / Decimal| Exact monetary amount rounded using `Decimal` `ROUND_HALF_UP` to 2 decimal places. |
| `currency` | String | Canonical uppercase ISO currency code. |
| `amount_band` | String | Derived categorical dimension:<br>• `low`: amount < 100.00<br>• `medium`: 100.00 <= amount < 1000.00<br>• `high`: amount >= 1000.00 |
| `updated_at_utc` | String (ISO-8601)| Record version timestamp in UTC (`YYYY-MM-DDTHH:MM:SSZ`). |
| `source_file` | String | Lineage: input file basename (`orders.csv`). |
| `run_id` | String | Lineage: deterministic execution run identifier (`run_<sha256[:12]>`). |

---

## 3. Rejects & Quarantine Schema

Every record failing schema format, validation rules, or superseded during deduplication is quarantined to `rejects/<entity>_rejects.csv` preserving full traceability.

| Column | Description |
| :--- | :--- |
| `run_id` | Deterministic pipeline run ID. |
| `source_file` | Name of the file containing the rejected record. |
| `source_line_number` | 1-based line number in the source file. |
| `entity` | Target entity (`customers` or `orders`). |
| `business_key` | Extracted business key or `UNKNOWN`/`MISSING_KEY`. |
| `reason_code` | Machine-readable rejection code (e.g. `MALFORMED_ROW`, `INVALID_FK`, `DUPLICATE_SUPERSEDED`). |
| `reason_detail` | Detailed human-readable explanation of why the rule failed. |
| `raw_record` | Verbatim text row from the source extract. |
