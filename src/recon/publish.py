"""
Atomic, idempotent publishing with updated_at guard and transaction-like replacement.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Dict, List, Sequence
import pandas as pd

from recon.schemas import DIM_CUSTOMERS_COLUMNS, FACT_ORDERS_COLUMNS


@dataclass(frozen=True)
class PublishMetrics:
    inserted: int
    updated: int
    unchanged: int
    skipped_stale: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_stale": self.skipped_stale,
        }


def publish_dataset(
    incoming_df: pd.DataFrame,
    target_path: Path,
    pk_column: str,
    target_columns: Sequence[str],
) -> PublishMetrics:
    """Publishes transformed dataset idempotently with an updated_at guard and atomic file swap.

    Args:
        incoming_df: Newly transformed records for publishing.
        target_path: Destination path for the CSV (e.g. fact_orders.csv).
        pk_column: Primary business key (customer_id or order_id).
        target_columns: Ordered list of columns to be persisted.

    Returns:
        PublishMetrics tracking inserted, updated, unchanged, and skipped_stale counts.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not target_path.exists() or os.path.getsize(target_path) == 0:
        # First-time publish: all incoming records are inserted
        if incoming_df.empty:
            out_df = pd.DataFrame(columns=target_columns)
        else:
            out_df = incoming_df.sort_values(by=pk_column).reset_index(drop=True)
            out_df = out_df[list(target_columns)]

        _atomic_write_csv(out_df, target_path)
        return PublishMetrics(
            inserted=len(incoming_df),
            updated=0,
            unchanged=0,
            skipped_stale=0,
        )

    # Existing target present: load and perform guarded upsert
    existing_df = pd.read_csv(target_path, dtype=str).fillna("")
    existing_records = {row[pk_column]: row.to_dict() for _, row in existing_df.iterrows()}

    inserted = 0
    updated = 0
    unchanged = 0
    skipped_stale = 0

    incoming_dict = {row[pk_column]: row.to_dict() for _, row in incoming_df.iterrows()}

    # Non-lineage columns to check for true changes
    compare_cols = [c for c in target_columns if c not in ("run_id", "source_file")]

    final_records: Dict[str, dict] = dict(existing_records)

    for pk, in_row in incoming_dict.items():
        if pk not in final_records:
            final_records[pk] = in_row
            inserted += 1
        else:
            curr_row = final_records[pk]
            in_updated_at = str(in_row.get("updated_at_utc", ""))
            curr_updated_at = str(curr_row.get("updated_at_utc", ""))

            # Guarded upsert: late data with older updated_at must NOT overwrite newer data
            if in_updated_at < curr_updated_at:
                skipped_stale += 1
            else:
                # Check if payload actually changed
                is_changed = any(
                    str(in_row.get(col, "")).strip() != str(curr_row.get(col, "")).strip()
                    for col in compare_cols
                )
                if is_changed:
                    final_records[pk] = in_row
                    updated += 1
                else:
                    unchanged += 1

    # Deterministic output: sorted by PK
    out_list = sorted(final_records.values(), key=lambda r: str(r[pk_column]))
    out_df = pd.DataFrame(out_list, columns=target_columns) if out_list else pd.DataFrame(columns=target_columns)

    _atomic_write_csv(out_df, target_path)

    return PublishMetrics(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        skipped_stale=skipped_stale,
    )


def _atomic_write_csv(df: pd.DataFrame, target_path: Path) -> None:
    """Writes dataframe to a temporary file in the same directory and replaces atomically."""
    dir_name = target_path.parent
    fd, temp_file_path = tempfile.mkstemp(dir=str(dir_name), prefix="tmp_publish_", suffix=".csv")
    try:
        with open(fd, "w", encoding="utf-8", newline="") as f:
            df.to_csv(f, index=False)
        os.replace(temp_file_path, target_path)
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass


def publish_all(
    dim_customers_df: pd.DataFrame,
    fact_orders_df: pd.DataFrame,
    target_dir: Path,
) -> Dict[str, Dict[str, int]]:
    """Publishes dim_customers first, then fact_orders, enforcing dependency order."""
    target_dir.mkdir(parents=True, exist_ok=True)
    cust_metrics = publish_dataset(
        incoming_df=dim_customers_df,
        target_path=target_dir / "dim_customers.csv",
        pk_column="customer_id",
        target_columns=DIM_CUSTOMERS_COLUMNS,
    )
    orders_metrics = publish_dataset(
        incoming_df=fact_orders_df,
        target_path=target_dir / "fact_orders.csv",
        pk_column="order_id",
        target_columns=FACT_ORDERS_COLUMNS,
    )
    return {
        "customers": cust_metrics.to_dict(),
        "orders": orders_metrics.to_dict(),
    }
