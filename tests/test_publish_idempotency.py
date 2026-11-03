"""
Tests for atomic idempotent publishing and updated_at guard.
"""

import hashlib
from pathlib import Path
import pytest
import pandas as pd

from recon.publish import publish_dataset
from recon.schemas import FACT_ORDERS_COLUMNS


def _compute_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rerun_no_duplicates(tmp_path: Path):
    target_csv = tmp_path / "target" / "fact_orders.csv"

    records = [
        {
            "order_id": "O00000001",
            "customer_id": "C000001",
            "order_ts_utc": "2026-01-01T10:00:00Z",
            "order_date": "2026-01-01",
            "status": "paid",
            "amount": "100.00",
            "currency": "USD",
            "amount_band": "medium",
            "updated_at_utc": "2026-01-01T10:05:00Z",
            "source_file": "orders.csv",
            "run_id": "run_1",
        }
    ]
    df = pd.DataFrame(records, columns=FACT_ORDERS_COLUMNS)

    # First run
    m1 = publish_dataset(df, target_csv, "order_id", FACT_ORDERS_COLUMNS)
    assert m1.inserted == 1
    assert m1.updated == 0
    assert m1.unchanged == 0
    hash1 = _compute_hash(target_csv)

    # Second run (exact same input)
    m2 = publish_dataset(df, target_csv, "order_id", FACT_ORDERS_COLUMNS)
    assert m2.inserted == 0
    assert m2.updated == 0
    assert m2.unchanged == 1
    hash2 = _compute_hash(target_csv)

    assert hash1 == hash2


def test_stale_update_does_not_overwrite(tmp_path: Path):
    target_csv = tmp_path / "target" / "fact_orders.csv"

    # Initial state with newer updated_at
    records_newer = [
        {
            "order_id": "O00000001",
            "customer_id": "C000001",
            "order_ts_utc": "2026-01-01T10:00:00Z",
            "order_date": "2026-01-01",
            "status": "delivered",
            "amount": "100.00",
            "currency": "USD",
            "amount_band": "medium",
            "updated_at_utc": "2026-01-01T18:00:00Z",
            "source_file": "orders.csv",
            "run_id": "run_1",
        }
    ]
    publish_dataset(pd.DataFrame(records_newer, columns=FACT_ORDERS_COLUMNS), target_csv, "order_id", FACT_ORDERS_COLUMNS)

    # Late-arriving stale record with older updated_at
    records_stale = [
        {
            "order_id": "O00000001",
            "customer_id": "C000001",
            "order_ts_utc": "2026-01-01T10:00:00Z",
            "order_date": "2026-01-01",
            "status": "created",  # Old status
            "amount": "100.00",
            "currency": "USD",
            "amount_band": "medium",
            "updated_at_utc": "2026-01-01T10:05:00Z",  # Older timestamp
            "source_file": "orders.csv",
            "run_id": "run_2",
        }
    ]
    m_stale = publish_dataset(pd.DataFrame(records_stale, columns=FACT_ORDERS_COLUMNS), target_csv, "order_id", FACT_ORDERS_COLUMNS)

    assert m_stale.skipped_stale == 1
    assert m_stale.updated == 0

    # Ensure target still holds delivered status and 18:00:00Z
    final_df = pd.read_csv(target_csv)
    assert final_df.iloc[0]["status"] == "delivered"
    assert final_df.iloc[0]["updated_at_utc"] == "2026-01-01T18:00:00Z"



def test_publish_empty_dataframe(tmp_path: Path):
    target_csv = tmp_path / "target" / "fact_orders.csv"
    empty_df = pd.DataFrame(columns=FACT_ORDERS_COLUMNS)
    m = publish_dataset(empty_df, target_csv, "order_id", FACT_ORDERS_COLUMNS)
    assert m.inserted == 0
    assert target_csv.is_file()
    read_back = pd.read_csv(target_csv)
    assert len(read_back) == 0
    assert list(read_back.columns) == list(FACT_ORDERS_COLUMNS)
