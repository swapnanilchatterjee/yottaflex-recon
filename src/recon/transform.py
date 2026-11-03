"""
Deterministic transformations, normalisation, and derived field computations.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import pandas as pd

from recon.schemas import DIM_CUSTOMERS_COLUMNS, FACT_ORDERS_COLUMNS


def format_iso_utc(dt: datetime) -> str:
    """Formats datetime to ISO-8601 UTC string ending in 'Z'."""
    utc_dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def round_amount_half_up(amount_val: Decimal | str | float) -> Decimal:
    """Quantises amount to exactly 2 decimal places using ROUND_HALF_UP."""
    if not isinstance(amount_val, Decimal):
        amount_val = Decimal(str(amount_val))
    return amount_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_amount_band(amount: Decimal) -> str:
    """Derives amount_band based on exact decimal boundaries:

    - 'low': amount < 100.00
    - 'medium': 100.00 <= amount < 1000.00
    - 'high': amount >= 1000.00
    """
    if amount < Decimal("100.00"):
        return "low"
    elif amount < Decimal("1000.00"):
        return "medium"
    else:
        return "high"


def transform_customers(
    df: pd.DataFrame,
    run_id: str,
    source_file: str,
) -> pd.DataFrame:
    """Transforms valid customer records into dim_customers target schema."""
    if df.empty:
        return pd.DataFrame(columns=DIM_CUSTOMERS_COLUMNS)

    rows = []
    for _, row in df.iterrows():
        cid = str(row["customer_id"]).strip()
        cname = str(row["customer_name"]).strip()
        raw_email = row.get("email", "")
        email = str(raw_email).strip().lower() if pd.notna(raw_email) and str(raw_email).strip() else ""
        ccode = str(row["country_code"]).strip().upper()

        cat_dt: datetime = row["_created_at_dt"]
        uat_dt: datetime = row["_updated_at_dt"]

        rows.append(
            {
                "customer_id": cid,
                "customer_name": cname,
                "email": email,
                "country_code": ccode,
                "created_at_utc": format_iso_utc(cat_dt),
                "updated_at_utc": format_iso_utc(uat_dt),
                "source_file": source_file,
                "run_id": run_id,
            }
        )

    out_df = pd.DataFrame(rows, columns=DIM_CUSTOMERS_COLUMNS)
    # Deterministic sorting by customer_id
    out_df = out_df.sort_values(by="customer_id").reset_index(drop=True)
    return out_df


def transform_orders(
    df: pd.DataFrame,
    run_id: str,
    source_file: str,
) -> pd.DataFrame:
    """Transforms valid order records into fact_orders target schema."""
    if df.empty:
        return pd.DataFrame(columns=FACT_ORDERS_COLUMNS)

    rows = []
    for _, row in df.iterrows():
        oid = str(row["order_id"]).strip()
        cid = str(row["customer_id"]).strip()

        ots_dt: datetime = row["_order_ts_dt"]
        uat_dt: datetime = row["_updated_at_dt"]
        amt_raw: Decimal = row["_amount_dec"]

        amt_rounded = round_amount_half_up(amt_raw)
        band = compute_amount_band(amt_rounded)

        status_norm = str(row["status"]).strip().lower()
        currency_norm = str(row["currency"]).strip().upper()

        order_ts_utc = format_iso_utc(ots_dt)
        order_date = ots_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        updated_at_utc = format_iso_utc(uat_dt)

        rows.append(
            {
                "order_id": oid,
                "customer_id": cid,
                "order_ts_utc": order_ts_utc,
                "order_date": order_date,
                "status": status_norm,
                "amount": f"{amt_rounded:.2f}",
                "currency": currency_norm,
                "amount_band": band,
                "updated_at_utc": updated_at_utc,
                "source_file": source_file,
                "run_id": run_id,
            }
        )

    out_df = pd.DataFrame(rows, columns=FACT_ORDERS_COLUMNS)
    # Deterministic sorting by order_id
    out_df = out_df.sort_values(by="order_id").reset_index(drop=True)
    return out_df
