"""
Edge-case resilience tests: empty batches, missing columns, crash recovery, and retry behavior.
"""

from pathlib import Path
import pytest
import pandas as pd

from recon.cli import main
from recon.errors import SchemaError
from recon.ingest import ingest_csv
from recon.publish import publish_dataset
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    FACT_ORDERS_COLUMNS,
    SCHEMA_MISSING_COLUMNS,
)


def test_empty_batch(tmp_path: Path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    out_dir = tmp_path / "out"

    source_dir.mkdir(parents=True)
    # Header only files
    (source_dir / "customers.csv").write_text(
        "customer_id,customer_name,country_code,created_at,updated_at\n", encoding="utf-8"
    )
    (source_dir / "orders.csv").write_text(
        "order_id,customer_id,order_ts,status,amount,currency,updated_at\n", encoding="utf-8"
    )

    exit_code_run = main([
        "run",
        "--source-dir", str(source_dir),
        "--target-dir", str(target_dir),
        "--out-dir", str(out_dir),
    ])
    assert exit_code_run == 0

    exit_code_rec = main([
        "reconcile",
        "--source-dir", str(source_dir),
        "--target-dir", str(target_dir),
        "--out-dir", str(out_dir),
    ])
    assert exit_code_rec == 0


def test_missing_column_fails_run(tmp_path: Path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    out_dir = tmp_path / "out"

    source_dir.mkdir(parents=True)
    # Missing required country_code in customers
    (source_dir / "customers.csv").write_text("customer_id,customer_name\n", encoding="utf-8")
    (source_dir / "orders.csv").write_text("order_id,customer_id,order_ts,status,amount,currency,updated_at\n", encoding="utf-8")

    exit_code = main([
        "run",
        "--source-dir", str(source_dir),
        "--target-dir", str(target_dir),
        "--out-dir", str(out_dir),
    ])
    assert exit_code == 2


def test_publish_crash_leaves_target_intact_then_retry_succeeds(tmp_path: Path, monkeypatch):
    target_file = tmp_path / "fact_orders.csv"
    initial_record = [
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
            "run_id": "initial",
        }
    ]
    publish_dataset(pd.DataFrame(initial_record, columns=FACT_ORDERS_COLUMNS), target_file, "order_id", FACT_ORDERS_COLUMNS)
    content_before = target_file.read_text(encoding="utf-8")

    # Simulate crash during atomic swap
    import recon.publish

    def faulty_atomic_swap(df, path):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(recon.publish, "_atomic_write_csv", faulty_atomic_swap)

    new_record = [
        {
            "order_id": "O00000002",
            "customer_id": "C000001",
            "order_ts_utc": "2026-01-01T11:00:00Z",
            "order_date": "2026-01-01",
            "status": "paid",
            "amount": "200.00",
            "currency": "USD",
            "amount_band": "medium",
            "updated_at_utc": "2026-01-01T11:05:00Z",
            "source_file": "orders.csv",
            "run_id": "crash_run",
        }
    ]

    with pytest.raises(OSError):
        publish_dataset(pd.DataFrame(new_record, columns=FACT_ORDERS_COLUMNS), target_file, "order_id", FACT_ORDERS_COLUMNS)

    # Verify target file remained completely intact
    assert target_file.read_text(encoding="utf-8") == content_before

    # Now unpatch and retry; retry must succeed
    monkeypatch.undo()
    m = publish_dataset(pd.DataFrame(new_record, columns=FACT_ORDERS_COLUMNS), target_file, "order_id", FACT_ORDERS_COLUMNS)
    assert m.inserted == 1

    final_df = pd.read_csv(target_file)
    assert len(final_df) == 2
