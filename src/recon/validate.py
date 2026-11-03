"""
Validation rules, business key deduplication, foreign-key referential integrity, and reject quarantining.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import List, Optional, Set, Tuple
import pandas as pd

from recon.config import PipelineConfig
from recon.schemas import (
    COUNTRY_CODE_REGEX,
    CUSTOMER_ID_REGEX,
    DUPLICATE_SUPERSEDED,
    FUTURE_TIMESTAMP,
    INVALID_FK,
    INVALID_FORMAT,
    INVALID_TYPE,
    INVALID_VALUE,
    MAX_AMOUNT,
    MIN_AMOUNT,
    MISSING_REQUIRED,
    ORDER_ID_REGEX,
    REJECT_COLUMNS,
)

_CUSTOMER_ID_PAT = re.compile(CUSTOMER_ID_REGEX)
_ORDER_ID_PAT = re.compile(ORDER_ID_REGEX)
_COUNTRY_CODE_PAT = re.compile(COUNTRY_CODE_REGEX)


def parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    """Safely parses an ISO-8601 timestamp string into a UTC datetime object."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def validate_customers(
    df: pd.DataFrame,
    run_id: str,
    source_file: str,
    config: PipelineConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Validates customers dataframe row by row, applies deduplication, and extracts rejects."""
    if df.empty:
        empty_valid = pd.DataFrame(columns=list(df.columns) + ["_created_at_dt", "_updated_at_dt"])
        empty_rejects = pd.DataFrame(columns=REJECT_COLUMNS)
        return empty_valid, empty_rejects

    valid_records: List[dict] = []
    reject_records: List[dict] = []

    for _, row in df.iterrows():
        raw_rec = row.get("_raw_record", "")
        line_num = int(row.get("_source_line_number", 0))

        cid = str(row.get("customer_id", "")).strip()
        cname = str(row.get("customer_name", "")).strip()
        ccode = str(row.get("country_code", "")).strip()
        cat_str = str(row.get("created_at", "")).strip()
        uat_str = str(row.get("updated_at", "")).strip()

        # 1. Required fields
        if not cid or not cname or not ccode or not cat_str or not uat_str:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid or "MISSING_KEY",
                    "reason_code": MISSING_REQUIRED,
                    "reason_detail": "One or more required fields (customer_id, customer_name, country_code, created_at, updated_at) are blank",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 2. Format checks
        if not _CUSTOMER_ID_PAT.match(cid):
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid,
                    "reason_code": INVALID_FORMAT,
                    "reason_detail": f"customer_id '{cid}' does not match regex ^C\\d{{6}}$",
                    "raw_record": raw_rec,
                }
            )
            continue

        if not _COUNTRY_CODE_PAT.match(ccode):
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid,
                    "reason_code": INVALID_FORMAT,
                    "reason_detail": f"country_code '{ccode}' must be 2 alphabetic characters",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 3. Timestamp types
        cat_dt = parse_iso_timestamp(cat_str)
        if cat_dt is None:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid,
                    "reason_code": INVALID_TYPE,
                    "reason_detail": f"created_at '{cat_str}' is not a valid ISO-8601 timestamp",
                    "raw_record": raw_rec,
                }
            )
            continue

        uat_dt = parse_iso_timestamp(uat_str)
        if uat_dt is None:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid,
                    "reason_code": INVALID_TYPE,
                    "reason_detail": f"updated_at '{uat_str}' is not a valid ISO-8601 timestamp",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 4. Logical value constraints: updated_at >= created_at
        if uat_dt < cat_dt:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "customers",
                    "business_key": cid,
                    "reason_code": INVALID_VALUE,
                    "reason_detail": f"updated_at ({uat_str}) cannot be earlier than created_at ({cat_str})",
                    "raw_record": raw_rec,
                }
            )
            continue

        rec_dict = dict(row)
        rec_dict["_created_at_dt"] = cat_dt
        rec_dict["_updated_at_dt"] = uat_dt
        valid_records.append(rec_dict)

    # Deduplication pass: within batch by customer_id
    if valid_records:
        temp_df = pd.DataFrame(valid_records)
        # Sort by customer_id and updated_at_dt ascending, tie-breaker source_line_number
        temp_df = temp_df.sort_values(
            by=["customer_id", "_updated_at_dt", "_source_line_number"],
            ascending=[True, True, True],
        )

        dedup_valid = []
        for cid, group in temp_df.groupby("customer_id", sort=False):
            if len(group) == 1:
                dedup_valid.append(group.iloc[0].to_dict())
            else:
                # Keep the last one (highest updated_at, tie-break last in file)
                latest_row = group.iloc[-1]
                dedup_valid.append(latest_row.to_dict())
                # All superseded rows go to rejects
                for i in range(len(group) - 1):
                    superseded = group.iloc[i]
                    reject_records.append(
                        {
                            "run_id": run_id,
                            "source_file": source_file,
                            "source_line_number": int(superseded["_source_line_number"]),
                            "entity": "customers",
                            "business_key": cid,
                            "reason_code": DUPLICATE_SUPERSEDED,
                            "reason_detail": f"Superseded by version at line {latest_row['_source_line_number']}",
                            "raw_record": superseded.get("_raw_record", ""),
                        }
                    )
        valid_df = pd.DataFrame(dedup_valid)
    else:
        valid_df = pd.DataFrame(columns=list(df.columns) + ["_created_at_dt", "_updated_at_dt"])

    rejects_df = pd.DataFrame(reject_records) if reject_records else pd.DataFrame(columns=REJECT_COLUMNS)

    # Invariant assertion
    assert len(df) == len(valid_df) + len(rejects_df), (
        f"Customers invariant violated: input {len(df)} != valid {len(valid_df)} + rejects {len(rejects_df)}"
    )

    return valid_df, rejects_df


def validate_orders(
    df: pd.DataFrame,
    valid_customer_ids: Set[str],
    run_id: str,
    source_file: str,
    config: PipelineConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Validates orders dataframe row by row, applies deduplication, FK verification, and extracts rejects."""
    if df.empty:
        empty_valid = pd.DataFrame(
            columns=list(df.columns) + ["_order_ts_dt", "_updated_at_dt", "_amount_dec"]
        )
        empty_rejects = pd.DataFrame(columns=REJECT_COLUMNS)
        return empty_valid, empty_rejects

    valid_records: List[dict] = []
    reject_records: List[dict] = []
    now_utc = config.get_current_time()

    for _, row in df.iterrows():
        raw_rec = row.get("_raw_record", "")
        line_num = int(row.get("_source_line_number", 0))

        oid = str(row.get("order_id", "")).strip()
        cid = str(row.get("customer_id", "")).strip()
        ots_str = str(row.get("order_ts", "")).strip()
        status_str = str(row.get("status", "")).strip()
        amount_str = str(row.get("amount", "")).strip()
        currency_str = str(row.get("currency", "")).strip()
        uat_str = str(row.get("updated_at", "")).strip()

        # 1. Required fields
        if not oid or not cid or not ots_str or not status_str or not amount_str or not currency_str or not uat_str:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid or "MISSING_KEY",
                    "reason_code": MISSING_REQUIRED,
                    "reason_detail": "One or more required fields are blank",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 2. Format checks: order_id
        if not _ORDER_ID_PAT.match(oid):
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_FORMAT,
                    "reason_detail": f"order_id '{oid}' does not match regex ^O\\d{{8}}$",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 3. Type checks: timestamps
        ots_dt = parse_iso_timestamp(ots_str)
        if ots_dt is None:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_TYPE,
                    "reason_detail": f"order_ts '{ots_str}' is not a valid ISO-8601 timestamp",
                    "raw_record": raw_rec,
                }
            )
            continue

        uat_dt = parse_iso_timestamp(uat_str)
        if uat_dt is None:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_TYPE,
                    "reason_detail": f"updated_at '{uat_str}' is not a valid ISO-8601 timestamp",
                    "raw_record": raw_rec,
                }
            )
            continue

        # Decimal amount check
        try:
            amt_dec = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_TYPE,
                    "reason_detail": f"amount '{amount_str}' is not a valid decimal number",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 4. Value rules
        # Amount range
        if amt_dec < MIN_AMOUNT or amt_dec > MAX_AMOUNT:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_VALUE,
                    "reason_detail": f"amount {amt_dec} outside valid range [{MIN_AMOUNT}, {MAX_AMOUNT}]",
                    "raw_record": raw_rec,
                }
            )
            continue

        # Status check
        status_norm = status_str.lower()
        if status_norm not in config.allowed_statuses:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_VALUE,
                    "reason_detail": f"status '{status_str}' not in allowed set {sorted(config.allowed_statuses)}",
                    "raw_record": raw_rec,
                }
            )
            continue

        # Currency check
        currency_norm = currency_str.upper()
        if currency_norm not in config.allowed_currencies:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_VALUE,
                    "reason_detail": f"currency '{currency_str}' not in allowed set {sorted(config.allowed_currencies)}",
                    "raw_record": raw_rec,
                }
            )
            continue

        # Future timestamp check
        if ots_dt > now_utc:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": FUTURE_TIMESTAMP,
                    "reason_detail": f"order_ts {ots_str} is in the future relative to {now_utc.isoformat()}",
                    "raw_record": raw_rec,
                }
            )
            continue

        # 5. Referential integrity (FK to valid customers)
        if cid not in valid_customer_ids:
            reject_records.append(
                {
                    "run_id": run_id,
                    "source_file": source_file,
                    "source_line_number": line_num,
                    "entity": "orders",
                    "business_key": oid,
                    "reason_code": INVALID_FK,
                    "reason_detail": f"customer_id '{cid}' does not reference any valid customer",
                    "raw_record": raw_rec,
                }
            )
            continue

        rec_dict = dict(row)
        rec_dict["_order_ts_dt"] = ots_dt
        rec_dict["_updated_at_dt"] = uat_dt
        rec_dict["_amount_dec"] = amt_dec
        valid_records.append(rec_dict)

    # Deduplication pass: within batch by order_id
    if valid_records:
        temp_df = pd.DataFrame(valid_records)
        temp_df = temp_df.sort_values(
            by=["order_id", "_updated_at_dt", "_source_line_number"],
            ascending=[True, True, True],
        )

        dedup_valid = []
        for oid, group in temp_df.groupby("order_id", sort=False):
            if len(group) == 1:
                dedup_valid.append(group.iloc[0].to_dict())
            else:
                latest_row = group.iloc[-1]
                dedup_valid.append(latest_row.to_dict())
                for i in range(len(group) - 1):
                    superseded = group.iloc[i]
                    reject_records.append(
                        {
                            "run_id": run_id,
                            "source_file": source_file,
                            "source_line_number": int(superseded["_source_line_number"]),
                            "entity": "orders",
                            "business_key": oid,
                            "reason_code": DUPLICATE_SUPERSEDED,
                            "reason_detail": f"Superseded by version at line {latest_row['_source_line_number']}",
                            "raw_record": superseded.get("_raw_record", ""),
                        }
                    )
        valid_df = pd.DataFrame(dedup_valid)
    else:
        valid_df = pd.DataFrame(
            columns=list(df.columns) + ["_order_ts_dt", "_updated_at_dt", "_amount_dec"]
        )

    rejects_df = pd.DataFrame(reject_records) if reject_records else pd.DataFrame(columns=REJECT_COLUMNS)

    # Invariant assertion
    assert len(df) == len(valid_df) + len(rejects_df), (
        f"Orders invariant violated: input {len(df)} != valid {len(valid_df)} + rejects {len(rejects_df)}"
    )

    return valid_df, rejects_df
