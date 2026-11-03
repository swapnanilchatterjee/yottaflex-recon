"""
Tests for generator determinism and reconciliation vs injected defect labels.
"""

import hashlib
import json
from pathlib import Path
import pytest

from recon.config import ReconConfig
from recon.generator import generate_dataset
from recon.reconcile import run_reconciliation


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_seed_same_bytes(tmp_path: Path):
    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"

    generate_dataset(dir1, num_customers=30, num_orders=100, seed=12345)
    generate_dataset(dir2, num_customers=30, num_orders=100, seed=12345)

    files = [
        "source/customers.csv",
        "source/orders.csv",
        "target_drifted/dim_customers.csv",
        "target_drifted/fact_orders.csv",
        "expected/expected_findings.json",
    ]

    for rel_path in files:
        h1 = _hash_file(dir1 / rel_path)
        h2 = _hash_file(dir2 / rel_path)
        assert h1 == h2, f"Hash mismatch for {rel_path} between runs with same seed"


def test_recon_matches_injected_labels(tmp_path: Path):
    data_dir = tmp_path / "data"
    generate_dataset(data_dir, num_customers=50, num_orders=200, seed=42, inject_defects=True)

    expected_path = data_dir / "expected" / "expected_findings.json"
    with open(expected_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    target_drift_labels = expected["target_drift_findings"]

    config = ReconConfig(
        source_dir=data_dir / "source",
        target_dir=data_dir / "target_drifted",
        out_dir=tmp_path / "recon_out",
        amount_tolerance=0.005,
    )

    result = run_reconciliation(
        source_dir=data_dir / "source",
        target_dir=data_dir / "target_drifted",
        run_id="test_run",
        config=config,
    )

    orders_ent = result.entities["orders"]

    # 1. Missing keys
    assert set(orders_ent.missing_in_target_keys) == set(target_drift_labels["missing_in_target"])

    # 2. Extra keys
    assert set(orders_ent.extra_in_target_keys) == set(target_drift_labels["extra_in_target"])

    # 3. Duplicate keys in target
    assert set(orders_ent.duplicate_in_target_keys) == set(target_drift_labels["duplicate_in_target"])

    # 4. Field mismatches
    amt_mismatch_keys = {
        m["business_key"] for m in orders_ent.field_mismatches if m["column"] == "amount"
    }
    assert amt_mismatch_keys == set(target_drift_labels["amount_mismatches"])

    stat_mismatch_keys = {
        m["business_key"] for m in orders_ent.field_mismatches if m["column"] == "status"
    }
    assert stat_mismatch_keys == set(target_drift_labels["status_mismatches"])

    # Overall reconciliation should fail because defects are present
    assert result.passed is False
