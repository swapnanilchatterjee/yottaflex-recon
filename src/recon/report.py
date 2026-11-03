"""
Report serialization: structured JSON synthesis, CSV mismatch isolation, and rejects emission.
"""

import json
from pathlib import Path
from typing import Dict
import pandas as pd

from recon.reconcile import FullReconResult
from recon.schemas import REJECT_COLUMNS


def write_reconciliation_artifacts(result: FullReconResult, out_dir: Path) -> int:
    """Serializes reconciliation findings to disk.

    Writes:
      - reconciliation_report.json
      - mismatches/missing_in_target.csv
      - mismatches/extra_in_target.csv
      - mismatches/duplicate_in_target.csv
      - mismatches/field_mismatches.csv
      - rejects/customers_rejects.csv
      - rejects/orders_rejects.csv

    Returns:
      0 if reconciliation passed completely, 1 if differences were flagged.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    mismatches_dir = out_dir / "mismatches"
    rejects_dir = out_dir / "rejects"
    mismatches_dir.mkdir(parents=True, exist_ok=True)
    rejects_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write reconciliation_report.json
    report_json_path = out_dir / "reconciliation_report.json"
    report_dict = result.to_dict()
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2)

    # 2. Write key-level mismatch files
    missing_records = []
    extra_records = []
    duplicate_records = []
    field_mismatch_records = []

    for entity_name, ent in result.entities.items():
        for k in ent.missing_in_target_keys:
            missing_records.append({"entity": entity_name, "business_key": k})
        for k in ent.extra_in_target_keys:
            extra_records.append({"entity": entity_name, "business_key": k})
        for k in ent.duplicate_in_target_keys:
            duplicate_records.append({"entity": entity_name, "business_key": k})
        for m in ent.field_mismatches:
            field_mismatch_records.append(m)

    _write_or_empty_csv(
        missing_records,
        ["entity", "business_key"],
        mismatches_dir / "missing_in_target.csv",
    )
    _write_or_empty_csv(
        extra_records,
        ["entity", "business_key"],
        mismatches_dir / "extra_in_target.csv",
    )
    _write_or_empty_csv(
        duplicate_records,
        ["entity", "business_key"],
        mismatches_dir / "duplicate_in_target.csv",
    )
    _write_or_empty_csv(
        field_mismatch_records,
        ["entity", "business_key", "column", "source_value", "target_value", "mismatch_type"],
        mismatches_dir / "field_mismatches.csv",
    )

    # 3. Write rejects by entity
    for entity_name, rejects_df in result.rejects_by_entity.items():
        reject_file = rejects_dir / f"{entity_name}_rejects.csv"
        if not rejects_df.empty:
            rejects_df[REJECT_COLUMNS].to_csv(reject_file, index=False)
        else:
            pd.DataFrame(columns=REJECT_COLUMNS).to_csv(reject_file, index=False)

    return 0 if result.passed else 1


def _write_or_empty_csv(records: list, columns: list, target_path: Path) -> None:
    """Helper to persist DataFrame or blank schema CSV if no records exist."""
    if records:
        df = pd.DataFrame(records, columns=columns)
    else:
        df = pd.DataFrame(columns=columns)
    df.to_csv(target_path, index=False)
