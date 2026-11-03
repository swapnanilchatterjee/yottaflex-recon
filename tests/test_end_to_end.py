"""
End-to-end integration tests for generation, pipeline execution, and reconciliation verification.
"""

import json
from pathlib import Path
import pytest

from recon.cli import main


def test_happy_path_pipeline_and_reconcile(tmp_path: Path):
    sample_dir = tmp_path / "sample"
    target_dir = tmp_path / "target"
    out_dir = tmp_path / "mode_a_out"

    # 1. Generate clean datasets
    exit_gen = main([
        "generate",
        "--out", str(sample_dir),
        "--customers", "30",
        "--orders", "100",
        "--seed", "42",
    ])
    assert exit_gen == 0

    # 2. Execute pipeline
    exit_run = main([
        "run",
        "--source-dir", str(sample_dir / "source"),
        "--target-dir", str(target_dir),
        "--out-dir", str(out_dir),
    ])
    assert exit_run == 0

    # Verify manifest
    manifest_path = out_dir / "run_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "SUCCESS"
    assert manifest["output_counts"]["customers_published"] > 0
    assert manifest["output_counts"]["orders_published"] > 0

    # Verify published CSVs
    assert (target_dir / "dim_customers.csv").is_file()
    assert (target_dir / "fact_orders.csv").is_file()

    # 3. Reconcile against freshly published target
    exit_recon = main([
        "reconcile",
        "--source-dir", str(sample_dir / "source"),
        "--target-dir", str(target_dir),
        "--out-dir", str(out_dir),
    ])
    assert exit_recon == 0

    # Verify reconciliation report
    report_path = out_dir / "reconciliation_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["summary"]["total_mismatched_records"] == 0
    assert report["entities"]["customers"]["counts"]["unexplained_difference"] == 0
    assert report["entities"]["orders"]["counts"]["unexplained_difference"] == 0
