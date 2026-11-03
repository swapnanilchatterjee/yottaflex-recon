"""
Seeded synthetic data generator with deterministic defect injection and drifted targets.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd

from recon.config import PipelineConfig
from recon.ingest import ingest_csv
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    DIM_CUSTOMERS_COLUMNS,
    FACT_ORDERS_COLUMNS,
    ORDERS_ALL_COLUMNS,
    ORDERS_REQUIRED_COLUMNS,
)
from recon.transform import transform_customers, transform_orders
from recon.validate import validate_customers, validate_orders


def generate_dataset(
    out_dir: Path,
    num_customers: int = 50,
    num_orders: int = 200,
    seed: int = 42,
    inject_defects: bool = True,
) -> Dict[str, Path]:
    """Generates synthetic source datasets, drifted targets, and expected validation labels.

    Args:
        out_dir: Directory where source/, target_drifted/, and expected/ are created.
        num_customers: Base number of valid customers.
        num_orders: Base number of valid orders.
        seed: Random seed for deterministic reproducibility.
        inject_defects: Whether to inject edge-case defects into source and target.

    Returns:
        Dictionary of created paths.
    """
    rng = np.random.default_rng(seed)

    source_dir = out_dir / "source"
    target_drifted_dir = out_dir / "target_drifted"
    expected_dir = out_dir / "expected"

    source_dir.mkdir(parents=True, exist_ok=True)
    target_drifted_dir.mkdir(parents=True, exist_ok=True)
    expected_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate Customers
    customer_ids = [f"C{i:06d}" for i in range(1, num_customers + 1)]
    countries = ["US", "GB", "DE", "FR", "IN", "CA", "AU", "JP"]

    customer_rows: List[dict] = []
    for i, cid in enumerate(customer_ids, start=1):
        cname = f"Customer_{i}"
        email = f"user_{i}@example.com" if (i % 5 != 0) else ""  # Optional email
        country = countries[i % len(countries)]
        created_at = f"2026-01-{(i % 28) + 1:02d}T10:00:00Z"
        updated_at = f"2026-01-{(i % 28) + 1:02d}T12:00:00Z"
        customer_rows.append(
            {
                "customer_id": cid,
                "customer_name": cname,
                "email": email,
                "country_code": country,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

    # Injected customer defects if enabled
    customer_reject_labels = {}
    if inject_defects and num_customers >= 10:
        # Invalid format customer_id
        customer_rows.append(
            {
                "customer_id": "BAD_CUST_999",
                "customer_name": "Bad Customer",
                "email": "bad@example.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
            }
        )
        customer_reject_labels["invalid_format"] = ["BAD_CUST_999"]

        # Missing required country_code
        customer_rows.append(
            {
                "customer_id": "C999001",
                "customer_name": "Missing Country",
                "email": "no_country@example.com",
                "country_code": "",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
            }
        )
        customer_reject_labels["missing_required"] = ["C999001"]

        # Invalid updated_at < created_at
        customer_rows.append(
            {
                "customer_id": "C999002",
                "customer_name": "Backwards Time",
                "email": "back@example.com",
                "country_code": "US",
                "created_at": "2026-01-02T10:00:00Z",
                "updated_at": "2026-01-01T10:00:00Z",
            }
        )
        customer_reject_labels["invalid_value_time"] = ["C999002"]

    customers_csv_path = source_dir / "customers.csv"
    cust_df = pd.DataFrame(customer_rows)
    cust_df.to_csv(customers_csv_path, index=False)

    # 2. Generate Orders
    statuses = ["created", "paid", "shipped", "delivered", "cancelled", "refunded"]
    currencies = ["USD", "EUR", "INR", "GBP"]

    order_rows: List[dict] = []
    order_reject_labels: Dict[str, List[str]] = {
        "missing_required": [],
        "invalid_format": [],
        "invalid_value_amount": [],
        "invalid_value_status": [],
        "invalid_value_currency": [],
        "future_timestamp": [],
        "invalid_fk": [],
        "duplicate_superseded": [],
    }

    base_amounts = [
        "25.50",
        "99.99",
        "100.00",
        "499.50",
        "999.99",
        "1000.00",
        "1500.25",
        "0.00",
        "1000000.00",
    ]

    for i in range(1, num_orders + 1):
        oid = f"O{i:08d}"
        cid = customer_ids[(i - 1) % len(customer_ids)]
        day = (i % 25) + 1
        ots = f"2026-01-{day:02d}T08:00:00Z"
        status = statuses[i % len(statuses)]
        amt = base_amounts[i % len(base_amounts)]
        curr = currencies[i % len(currencies)]
        uat = f"2026-01-{day:02d}T08:30:00Z"

        # Inject noise: occasional whitespace / casing to test transform normalisation
        if i % 7 == 0:
            status = f" {status.upper()} "
        if i % 11 == 0:
            curr = f" {curr.lower()} "
        # Inject timezone offset (+05:30) to test UTC normalisation
        if i % 13 == 0:
            ots = f"2026-01-{day:02d}T13:30:00+05:30"

        order_rows.append(
            {
                "order_id": oid,
                "customer_id": cid,
                "order_ts": ots,
                "status": status,
                "amount": amt,
                "currency": curr,
                "updated_at": uat,
            }
        )

    # Injected order defects
    if inject_defects and num_orders >= 20:
        # 1. Negative amount
        order_rows.append(
            {
                "order_id": "O99000001",
                "customer_id": customer_ids[0],
                "order_ts": "2026-01-05T10:00:00Z",
                "status": "paid",
                "amount": "-50.00",
                "currency": "USD",
                "updated_at": "2026-01-05T10:05:00Z",
            }
        )
        order_reject_labels["invalid_value_amount"].append("O99000001")

        # 2. Bad status
        order_rows.append(
            {
                "order_id": "O99000002",
                "customer_id": customer_ids[0],
                "order_ts": "2026-01-05T10:00:00Z",
                "status": "in_progress",
                "amount": "120.00",
                "currency": "USD",
                "updated_at": "2026-01-05T10:05:00Z",
            }
        )
        order_reject_labels["invalid_value_status"].append("O99000002")

        # 3. Bad currency
        order_rows.append(
            {
                "order_id": "O99000003",
                "customer_id": customer_ids[0],
                "order_ts": "2026-01-05T10:00:00Z",
                "status": "paid",
                "amount": "120.00",
                "currency": "BITCOIN",
                "updated_at": "2026-01-05T10:05:00Z",
            }
        )
        order_reject_labels["invalid_value_currency"].append("O99000003")

        # 4. Orphan customer_id (not in customer_ids)
        order_rows.append(
            {
                "order_id": "O99000004",
                "customer_id": "C999999",
                "order_ts": "2026-01-05T10:00:00Z",
                "status": "paid",
                "amount": "75.00",
                "currency": "USD",
                "updated_at": "2026-01-05T10:05:00Z",
            }
        )
        order_reject_labels["invalid_fk"].append("O99000004")

        # 5. Future timestamp
        order_rows.append(
            {
                "order_id": "O99000005",
                "customer_id": customer_ids[0],
                "order_ts": "2030-01-01T10:00:00Z",
                "status": "paid",
                "amount": "80.00",
                "currency": "USD",
                "updated_at": "2030-01-01T10:05:00Z",
            }
        )
        order_reject_labels["future_timestamp"].append("O99000005")

        # 6. Duplicate order_id with older updated_at (superseded)
        order_rows.append(
            {
                "order_id": "O00000001",
                "customer_id": customer_ids[0],
                "order_ts": "2026-01-01T08:00:00Z",
                "status": "created",
                "amount": "10.00",
                "currency": "USD",
                "updated_at": "2026-01-01T08:15:00Z",  # older than 08:30:00Z
            }
        )
        order_reject_labels["duplicate_superseded"].append("O00000001")

        # 7. Missing required field
        order_rows.append(
            {
                "order_id": "O99000007",
                "customer_id": customer_ids[0],
                "order_ts": "",
                "status": "paid",
                "amount": "100.00",
                "currency": "USD",
                "updated_at": "2026-01-01T08:15:00Z",
            }
        )
        order_reject_labels["missing_required"].append("O99000007")

    orders_csv_path = source_dir / "orders.csv"
    orders_df = pd.DataFrame(order_rows)
    orders_df.to_csv(orders_csv_path, index=False)

    # 3. Create Target Drifted (deliberate defects in target to test Mode B)
    # First, generate correct expected target via the pipeline modules
    pipeline_cfg = PipelineConfig(
        source_dir=source_dir,
        target_dir=target_drifted_dir,
        out_dir=out_dir,
    )
    raw_c, _ = ingest_csv(customers_csv_path, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "gen")
    val_c, _ = validate_customers(raw_c, "gen", customers_csv_path.name, pipeline_cfg)
    exp_tgt_c = transform_customers(val_c, "gen", customers_csv_path.name)

    raw_o, _ = ingest_csv(orders_csv_path, "orders", ORDERS_REQUIRED_COLUMNS, ORDERS_ALL_COLUMNS, "gen")
    val_c_ids = set(val_c["customer_id"].astype(str))
    val_o, _ = validate_orders(raw_o, val_c_ids, "gen", orders_csv_path.name, pipeline_cfg)
    exp_tgt_o = transform_orders(val_o, "gen", orders_csv_path.name)

    # Apply known drift mutations to fact_orders
    drift_labels = {
        "missing_in_target": [],
        "extra_in_target": [],
        "duplicate_in_target": [],
        "amount_mismatches": [],
        "status_mismatches": [],
    }

    drifted_orders = exp_tgt_o.copy()

    if inject_defects and len(drifted_orders) >= 10:
        # 1. Delete 2 rows (missing_in_target)
        del_pks = [drifted_orders.iloc[2]["order_id"], drifted_orders.iloc[3]["order_id"]]
        drift_labels["missing_in_target"] = del_pks
        drifted_orders = drifted_orders[~drifted_orders["order_id"].isin(del_pks)].copy()

        # 2. Add 2 extra rows (extra_in_target)
        extra_row_1 = {
            "order_id": "O_EXTRA_9001",
            "customer_id": customer_ids[0],
            "order_ts_utc": "2026-01-10T12:00:00Z",
            "order_date": "2026-01-10",
            "status": "paid",
            "amount": "999.00",
            "currency": "USD",
            "amount_band": "medium",
            "updated_at_utc": "2026-01-10T12:00:00Z",
            "source_file": "orders.csv",
            "run_id": "gen",
        }
        extra_row_2 = {
            "order_id": "O_EXTRA_9002",
            "customer_id": customer_ids[0],
            "order_ts_utc": "2026-01-10T12:00:00Z",
            "order_date": "2026-01-10",
            "status": "delivered",
            "amount": "50.00",
            "currency": "USD",
            "amount_band": "low",
            "updated_at_utc": "2026-01-10T12:00:00Z",
            "source_file": "orders.csv",
            "run_id": "gen",
        }
        drift_labels["extra_in_target"] = ["O_EXTRA_9001", "O_EXTRA_9002"]
        drifted_orders = pd.concat([drifted_orders, pd.DataFrame([extra_row_1, extra_row_2])], ignore_index=True)

        # 3. Duplicate 1 row in target (duplicate_in_target)
        dup_row = drifted_orders.iloc[0].to_dict()
        drift_labels["duplicate_in_target"] = [str(dup_row["order_id"])]
        drifted_orders = pd.concat([drifted_orders, pd.DataFrame([dup_row])], ignore_index=True)

        # 4. Modify amount on 1 row (field mismatch > tolerance)
        idx_amt = 4
        pk_amt = drifted_orders.iloc[idx_amt]["order_id"]
        orig_amt = float(drifted_orders.iloc[idx_amt]["amount"])
        drifted_orders.at[idx_amt, "amount"] = f"{orig_amt + 15.00:.2f}"
        drift_labels["amount_mismatches"] = [str(pk_amt)]

        # 5. Modify status on 1 row (field mismatch)
        idx_stat = 6
        pk_stat = drifted_orders.iloc[idx_stat]["order_id"]
        drifted_orders.at[idx_stat, "status"] = "cancelled"
        drift_labels["status_mismatches"] = [str(pk_stat)]

    # Write drifted targets
    exp_tgt_c.to_csv(target_drifted_dir / "dim_customers.csv", index=False)
    drifted_orders.to_csv(target_drifted_dir / "fact_orders.csv", index=False)

    # 4. Write expected_findings.json
    expected_findings = {
        "metadata": {
            "seed": seed,
            "num_customers": num_customers,
            "num_orders": num_orders,
        },
        "source_rejects": {
            "customers": customer_reject_labels,
            "orders": order_reject_labels,
        },
        "target_drift_findings": drift_labels,
    }
    with open(expected_dir / "expected_findings.json", "w", encoding="utf-8") as f:
        json.dump(expected_findings, f, indent=2)

    return {
        "source_customers": customers_csv_path,
        "source_orders": orders_csv_path,
        "drifted_customers": target_drifted_dir / "dim_customers.csv",
        "drifted_orders": target_drifted_dir / "fact_orders.csv",
        "expected_findings": expected_dir / "expected_findings.json",
    }
