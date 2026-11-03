"""
Reconciliation engine: counts, keys, aggregates, and vectorised field-level checks.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

from recon.config import PipelineConfig, ReconConfig
from recon.ingest import ingest_csv
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    ORDERS_ALL_COLUMNS,
    ORDERS_REQUIRED_COLUMNS,
    RECON_EXCLUDE_COLUMNS,
    REJECT_COLUMNS,
)
from recon.transform import transform_customers, transform_orders
from recon.validate import parse_iso_timestamp, validate_customers, validate_orders


@dataclass
class EntityReconResult:
    entity: str
    pk_col: str
    source_raw_count: int
    rejected_count: int
    expected_target_count: int
    actual_target_count: int
    unexplained_difference: int
    missing_in_target_keys: List[str]
    extra_in_target_keys: List[str]
    duplicate_in_target_keys: List[str]
    aggregates: List[Dict[str, Any]]
    field_mismatches: List[Dict[str, Any]]
    compared_rows: int
    mismatched_rows_count: int

    @property
    def passed(self) -> bool:
        if self.unexplained_difference != 0:
            return False
        if self.missing_in_target_keys or self.extra_in_target_keys or self.duplicate_in_target_keys:
            return False
        if any(not agg.get("pass", True) for agg in self.aggregates):
            return False
        if self.field_mismatches:
            return False
        return True


@dataclass
class FullReconResult:
    run_id: str
    tolerance_amount: float
    entities: Dict[str, EntityReconResult]
    rejects_by_entity: Dict[str, pd.DataFrame]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    @property
    def passed(self) -> bool:
        return all(ent.passed for ent in self.entities.values())

    @property
    def total_mismatches(self) -> int:
        total = 0
        for ent in self.entities.values():
            total += len(ent.missing_in_target_keys)
            total += len(ent.extra_in_target_keys)
            total += len(ent.duplicate_in_target_keys)
            total += ent.mismatched_rows_count
            total += abs(ent.unexplained_difference)
        return total

    def to_dict(self) -> Dict[str, Any]:
        failed_checks = []
        for name, ent in self.entities.items():
            if ent.unexplained_difference != 0:
                failed_checks.append(f"{name}:unexplained_count_diff({ent.unexplained_difference})")
            if ent.missing_in_target_keys:
                failed_checks.append(f"{name}:missing_keys({len(ent.missing_in_target_keys)})")
            if ent.extra_in_target_keys:
                failed_checks.append(f"{name}:extra_keys({len(ent.extra_in_target_keys)})")
            if ent.duplicate_in_target_keys:
                failed_checks.append(f"{name}:duplicate_target_keys({len(ent.duplicate_in_target_keys)})")
            for agg in ent.aggregates:
                if not agg.get("pass", True):
                    failed_checks.append(f"{name}:agg_{agg['name']}")
            if ent.field_mismatches:
                failed_checks.append(f"{name}:field_mismatches({len(ent.field_mismatches)})")

        entities_dict = {}
        for name, ent in self.entities.items():
            # Group field mismatches by column
            by_col: Dict[str, int] = {}
            for m in ent.field_mismatches:
                col = m["column"]
                by_col[col] = by_col.get(col, 0) + 1

            entities_dict[name] = {
                "counts": {
                    "source_raw": ent.source_raw_count,
                    "rejected": ent.rejected_count,
                    "expected_target": ent.expected_target_count,
                    "actual_target": ent.actual_target_count,
                    "unexplained_difference": ent.unexplained_difference,
                },
                "keys": {
                    "missing_in_target": len(ent.missing_in_target_keys),
                    "extra_in_target": len(ent.extra_in_target_keys),
                    "duplicate_in_target": len(ent.duplicate_in_target_keys),
                },
                "aggregates": ent.aggregates,
                "field_checks": {
                    "compared_rows": ent.compared_rows,
                    "mismatched_rows": ent.mismatched_rows_count,
                    "by_column": by_col,
                },
            }

        return {
            "report_version": "1.0",
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "status": "PASS" if self.passed else "FAIL",
            "tolerance": {"amount": self.tolerance_amount},
            "entities": entities_dict,
            "summary": {
                "total_mismatched_records": self.total_mismatches,
                "checks_failed": failed_checks,
            },
        }


def run_reconciliation(
    source_dir: Path,
    target_dir: Path,
    run_id: str,
    config: ReconConfig,
) -> FullReconResult:
    """Executes full 4-tier reconciliation between source directory and target directory."""
    pipeline_cfg = PipelineConfig(
        source_dir=source_dir,
        target_dir=target_dir,
        out_dir=config.out_dir,
        amount_tolerance=config.amount_tolerance,
        now_utc=config.now_utc,
    )

    cust_src_file = source_dir / "customers.csv"
    orders_src_file = source_dir / "orders.csv"

    # 1. Ingest source
    raw_cust_df, ingest_cust_rejects = ingest_csv(
        file_path=cust_src_file,
        entity="customers",
        required_columns=CUSTOMERS_REQUIRED_COLUMNS,
        all_known_columns=CUSTOMERS_ALL_COLUMNS,
        run_id=run_id,
    )

    raw_orders_df, ingest_orders_rejects = ingest_csv(
        file_path=orders_src_file,
        entity="orders",
        required_columns=ORDERS_REQUIRED_COLUMNS,
        all_known_columns=ORDERS_ALL_COLUMNS,
        run_id=run_id,
    )

    # 2. Validate in-memory
    valid_cust_df, val_cust_rejects = validate_customers(
        raw_cust_df,
        run_id=run_id,
        source_file=cust_src_file.name,
        config=pipeline_cfg,
    )
    all_cust_rejects = pd.concat([ingest_cust_rejects, val_cust_rejects], ignore_index=True)

    valid_cust_ids = set(valid_cust_df["customer_id"].astype(str)) if not valid_cust_df.empty else set()
    valid_orders_df, val_orders_rejects = validate_orders(
        raw_orders_df,
        valid_customer_ids=valid_cust_ids,
        run_id=run_id,
        source_file=orders_src_file.name,
        config=pipeline_cfg,
    )
    all_orders_rejects = pd.concat([ingest_orders_rejects, val_orders_rejects], ignore_index=True)

    # 3. Transform in-memory to get expected target datasets
    expected_cust_df = transform_customers(valid_cust_df, run_id=run_id, source_file=cust_src_file.name)
    expected_orders_df = transform_orders(valid_orders_df, run_id=run_id, source_file=orders_src_file.name)

    # 4. Load actual target datasets
    actual_cust_path = target_dir / "dim_customers.csv"
    actual_orders_path = target_dir / "fact_orders.csv"

    actual_cust_df = (
        pd.read_csv(actual_cust_path, dtype=str).fillna("")
        if actual_cust_path.is_file() and actual_cust_path.stat().st_size > 0
        else pd.DataFrame(columns=expected_cust_df.columns)
    )

    actual_orders_df = (
        pd.read_csv(actual_orders_path, dtype=str).fillna("")
        if actual_orders_path.is_file() and actual_orders_path.stat().st_size > 0
        else pd.DataFrame(columns=expected_orders_df.columns)
    )

    # 5. Reconcile customers
    cust_res = _reconcile_entity(
        entity_name="customers",
        pk_col="customer_id",
        source_raw_count=len(raw_cust_df) + len(ingest_cust_rejects),
        rejected_count=len(all_cust_rejects),
        expected_df=expected_cust_df,
        actual_df=actual_cust_df,
        amount_tolerance=config.amount_tolerance,
    )

    # 6. Reconcile orders
    orders_res = _reconcile_entity(
        entity_name="orders",
        pk_col="order_id",
        source_raw_count=len(raw_orders_df) + len(ingest_orders_rejects),
        rejected_count=len(all_orders_rejects),
        expected_df=expected_orders_df,
        actual_df=actual_orders_df,
        amount_tolerance=config.amount_tolerance,
    )

    return FullReconResult(
        run_id=run_id,
        tolerance_amount=config.amount_tolerance,
        entities={"customers": cust_res, "orders": orders_res},
        rejects_by_entity={"customers": all_cust_rejects, "orders": all_orders_rejects},
    )


def _reconcile_entity(
    entity_name: str,
    pk_col: str,
    source_raw_count: int,
    rejected_count: int,
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    amount_tolerance: float,
) -> EntityReconResult:
    """Executes count equation, key sets, aggregates, and field-level comparisons for an entity."""
    expected_target_count = len(expected_df)
    actual_target_count = len(actual_df)

    # Count equation:
    # source_raw_rows = expected_target_rows + rejected_rows
    # unexplained_difference = actual_target_rows - expected_target_rows
    unexplained_diff = actual_target_count - expected_target_count

    # Key sets
    exp_keys_series = expected_df[pk_col].astype(str) if not expected_df.empty else pd.Series(dtype=str)
    act_keys_series = actual_df[pk_col].astype(str) if not actual_df.empty else pd.Series(dtype=str)

    exp_keys_set = set(exp_keys_series)
    act_keys_set = set(act_keys_series)

    missing_in_target = sorted(list(exp_keys_set - act_keys_set))
    extra_in_target = sorted(list(act_keys_set - exp_keys_set))

    # Duplicate keys in actual target
    duplicate_in_target = []
    if not actual_df.empty and pk_col in actual_df.columns:
        counts = actual_df[pk_col].astype(str).value_counts()
        duplicate_in_target = sorted(counts[counts > 1].index.tolist())

    # Aggregates
    aggregates = _compute_aggregates(
        entity_name=entity_name,
        expected_df=expected_df,
        actual_df=actual_df,
        amount_tolerance=amount_tolerance,
    )

    # Field-level comparison on inner-joined keys
    field_mismatches, compared_rows, mismatched_rows_count = _compare_fields_vectorised(
        entity_name=entity_name,
        pk_col=pk_col,
        expected_df=expected_df,
        actual_df=actual_df,
        amount_tolerance=amount_tolerance,
    )

    return EntityReconResult(
        entity=entity_name,
        pk_col=pk_col,
        source_raw_count=source_raw_count,
        rejected_count=rejected_count,
        expected_target_count=expected_target_count,
        actual_target_count=actual_target_count,
        unexplained_difference=unexplained_diff,
        missing_in_target_keys=missing_in_target,
        extra_in_target_keys=extra_in_target,
        duplicate_in_target_keys=duplicate_in_target,
        aggregates=aggregates,
        field_mismatches=field_mismatches,
        compared_rows=compared_rows,
        mismatched_rows_count=mismatched_rows_count,
    )


def _compute_aggregates(
    entity_name: str,
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    amount_tolerance: float,
) -> List[Dict[str, Any]]:
    """Calculates domain aggregate checks and evaluates pass/fail status."""
    aggs = []

    # 1. Total row count aggregate
    exp_count = len(expected_df)
    act_count = len(actual_df)
    aggs.append(
        {
            "name": "row_count",
            "source": exp_count,
            "target": act_count,
            "diff": act_count - exp_count,
            "pass": (exp_count == act_count),
        }
    )

    if entity_name == "customers":
        # Distinct country code count
        exp_countries = (
            expected_df["country_code"].str.upper().nunique() if "country_code" in expected_df else 0
        )
        act_countries = (
            actual_df["country_code"].str.upper().nunique() if "country_code" in actual_df else 0
        )
        aggs.append(
            {
                "name": "distinct_countries",
                "source": exp_countries,
                "target": act_countries,
                "diff": act_countries - exp_countries,
                "pass": (exp_countries == act_countries),
            }
        )

    elif entity_name == "orders":
        # Sum of amount
        exp_sum = (
            float(pd.to_numeric(expected_df["amount"], errors="coerce").fillna(0).sum())
            if not expected_df.empty and "amount" in expected_df
            else 0.0
        )
        act_sum = (
            float(pd.to_numeric(actual_df["amount"], errors="coerce").fillna(0).sum())
            if not actual_df.empty and "amount" in actual_df
            else 0.0
        )
        sum_diff = round(act_sum - exp_sum, 4)
        aggs.append(
            {
                "name": "sum_amount",
                "source": round(exp_sum, 2),
                "target": round(act_sum, 2),
                "diff": sum_diff,
                "pass": (abs(sum_diff) <= amount_tolerance),
            }
        )

        # Min / Max amount
        exp_min = (
            float(pd.to_numeric(expected_df["amount"], errors="coerce").min())
            if not expected_df.empty and "amount" in expected_df
            else 0.0
        )
        act_min = (
            float(pd.to_numeric(actual_df["amount"], errors="coerce").min())
            if not actual_df.empty and "amount" in actual_df
            else 0.0
        )
        aggs.append(
            {
                "name": "min_amount",
                "source": round(exp_min, 2),
                "target": round(act_min, 2),
                "diff": round(act_min - exp_min, 4),
                "pass": (abs(act_min - exp_min) <= amount_tolerance),
            }
        )

        exp_max = (
            float(pd.to_numeric(expected_df["amount"], errors="coerce").max())
            if not expected_df.empty and "amount" in expected_df
            else 0.0
        )
        act_max = (
            float(pd.to_numeric(actual_df["amount"], errors="coerce").max())
            if not actual_df.empty and "amount" in actual_df
            else 0.0
        )
        aggs.append(
            {
                "name": "max_amount",
                "source": round(exp_max, 2),
                "target": round(act_max, 2),
                "diff": round(act_max - exp_max, 4),
                "pass": (abs(act_max - exp_max) <= amount_tolerance),
            }
        )

        # Distinct customer_ids in orders
        exp_custs = (
            expected_df["customer_id"].astype(str).nunique()
            if not expected_df.empty and "customer_id" in expected_df
            else 0
        )
        act_custs = (
            actual_df["customer_id"].astype(str).nunique()
            if not actual_df.empty and "customer_id" in actual_df
            else 0
        )
        aggs.append(
            {
                "name": "distinct_customers",
                "source": exp_custs,
                "target": act_custs,
                "diff": act_custs - exp_custs,
                "pass": (exp_custs == act_custs),
            }
        )

    return aggs


def _compare_fields_vectorised(
    entity_name: str,
    pk_col: str,
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    amount_tolerance: float,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Performs fast vectorised comparison of fields on matched business keys."""
    if expected_df.empty or actual_df.empty:
        return [], 0, 0

    # Non-lineage columns to compare
    compare_columns = [
        col
        for col in expected_df.columns
        if col not in RECON_EXCLUDE_COLUMNS and col in actual_df.columns and col != pk_col
    ]

    # De-duplicate actual_df on PK before inner join to avoid cartesian blowup
    act_dedup = actual_df.drop_duplicates(subset=[pk_col], keep="first")
    exp_dedup = expected_df.drop_duplicates(subset=[pk_col], keep="first")

    merged = pd.merge(
        exp_dedup[[pk_col] + compare_columns],
        act_dedup[[pk_col] + compare_columns],
        on=pk_col,
        suffixes=("_src", "_tgt"),
    )

    compared_rows = len(merged)
    if compared_rows == 0:
        return [], 0, 0

    mismatches: List[Dict[str, Any]] = []
    mismatched_pks: Set[str] = set()

    for col in compare_columns:
        src_series = merged[f"{col}_src"].astype(str).str.strip()
        tgt_series = merged[f"{col}_tgt"].astype(str).str.strip()

        if col == "amount":
            # Compare numerically within tolerance
            src_num = pd.to_numeric(src_series, errors="coerce").fillna(0.0)
            tgt_num = pd.to_numeric(tgt_series, errors="coerce").fillna(0.0)
            diff = (src_num - tgt_num).abs()
            mask_diff = diff > amount_tolerance
        else:
            # Exact string comparison
            mask_diff = src_series != tgt_series

        if mask_diff.any():
            diff_rows = merged[mask_diff]
            for _, r in diff_rows.iterrows():
                pk_val = str(r[pk_col])
                mismatches.append(
                    {
                        "entity": entity_name,
                        "business_key": pk_val,
                        "column": col,
                        "source_value": str(r[f"{col}_src"]),
                        "target_value": str(r[f"{col}_tgt"]),
                        "mismatch_type": "NUMERIC_DIFF" if col == "amount" else "VALUE_MISMATCH",
                    }
                )
                mismatched_pks.add(pk_val)

    return mismatches, compared_rows, len(mismatched_pks)
