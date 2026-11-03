"""
Tests for 4-tier reconciliation engine (counts, keys, aggregates, and field-level comparisons).
"""

from pathlib import Path
import pytest
import pandas as pd

from recon.config import ReconConfig
from recon.reconcile import _compare_fields_vectorised, _compute_aggregates, run_reconciliation
from recon.schemas import FACT_ORDERS_COLUMNS


def test_amount_tolerance():
    exp_df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "status": "paid",
                "amount": "100.000",
                "currency": "USD",
                "run_id": "r1",
                "source_file": "orders.csv",
            }
        ]
    )

    # 1. Diff within tolerance (0.004 <= 0.005)
    act_df_pass = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "status": "paid",
                "amount": "100.004",
                "currency": "USD",
                "run_id": "r2",
                "source_file": "orders.csv",
            }
        ]
    )
    mismatches, _, _ = _compare_fields_vectorised("orders", "order_id", exp_df, act_df_pass, 0.005)
    assert len(mismatches) == 0

    # 2. Diff exceeding tolerance (0.006 > 0.005)
    act_df_fail = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "status": "paid",
                "amount": "100.006",
                "currency": "USD",
                "run_id": "r2",
                "source_file": "orders.csv",
            }
        ]
    )
    mismatches, _, _ = _compare_fields_vectorised("orders", "order_id", exp_df, act_df_fail, 0.005)
    assert len(mismatches) == 1
    assert mismatches[0]["column"] == "amount"
    assert mismatches[0]["mismatch_type"] == "NUMERIC_DIFF"


def test_aggregate_mismatch_flagged():
    exp_df = pd.DataFrame([{"amount": "100.00", "customer_id": "C000001"}])
    act_df = pd.DataFrame([{"amount": "120.00", "customer_id": "C000001"}])

    aggs = _compute_aggregates("orders", exp_df, act_df, 0.005)
    sum_agg = next(a for a in aggs if a["name"] == "sum_amount")
    assert sum_agg["pass"] is False
    assert sum_agg["diff"] == 20.0


def test_key_differences():
    exp_df = pd.DataFrame(
        [
            {"order_id": "O00000001", "status": "paid"},
            {"order_id": "O00000002", "status": "paid"},
        ]
    )
    act_df = pd.DataFrame(
        [
            {"order_id": "O00000002", "status": "paid"},
            {"order_id": "O00000003", "status": "paid"},  # Extra
        ]
    )

    exp_keys = set(exp_df["order_id"])
    act_keys = set(act_df["order_id"])

    missing = exp_keys - act_keys
    extra = act_keys - exp_keys

    assert missing == {"O00000001"}
    assert extra == {"O00000003"}



def test_reconcile_handles_missing_target_file_gracefully(tmp_path: Path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "empty_target"
    out_dir = tmp_path / "recon_out"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)

    (source_dir / "customers.csv").write_text(
        "customer_id,customer_name,country_code,created_at,updated_at\n"
        "C000001,Alice,US,2026-01-01T10:00:00Z,2026-01-01T12:00:00Z\n",
        encoding="utf-8",
    )
    (source_dir / "orders.csv").write_text(
        "order_id,customer_id,order_ts,status,amount,currency,updated_at\n"
        "O00000001,C000001,2026-01-01T10:00:00Z,paid,50.00,USD,2026-01-01T10:05:00Z\n",
        encoding="utf-8",
    )

    config = ReconConfig(source_dir=source_dir, target_dir=target_dir, out_dir=out_dir)
    res = run_reconciliation(source_dir, target_dir, "run_missing", config)

    assert res.passed is False
    assert res.entities["orders"].actual_target_count == 0
    assert "O00000001" in res.entities["orders"].missing_in_target_keys
