"""
Unit tests for deterministic transforms and derived field calculation.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pandas as pd

from recon.transform import (
    compute_amount_band,
    format_iso_utc,
    round_amount_half_up,
    transform_customers,
    transform_orders,
)
from recon.validate import parse_iso_timestamp


def test_amount_rounding_half_up():
    assert round_amount_half_up(Decimal("10.005")) == Decimal("10.01")
    assert round_amount_half_up(Decimal("10.004")) == Decimal("10.00")
    assert round_amount_half_up("25.555") == Decimal("25.56")


def test_band_boundaries():
    assert compute_amount_band(Decimal("99.99")) == "low"
    assert compute_amount_band(Decimal("100.00")) == "medium"
    assert compute_amount_band(Decimal("999.99")) == "medium"
    assert compute_amount_band(Decimal("1000.00")) == "high"


def test_offset_to_utc():
    parsed = parse_iso_timestamp("2026-01-01T05:30:00+05:30")
    assert parsed is not None
    assert format_iso_utc(parsed) == "2026-01-01T00:00:00Z"


def test_status_currency_normalised():
    df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "_order_ts_dt": datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                "_updated_at_dt": datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
                "_amount_dec": Decimal("149.995"),
                "status": " PAID ",
                "currency": "usd",
            }
        ]
    )
    res = transform_orders(df, "run_test", "orders.csv")
    assert len(res) == 1
    row = res.iloc[0]
    assert row["status"] == "paid"
    assert row["currency"] == "USD"
    assert row["amount"] == "150.00"
    assert row["amount_band"] == "medium"
    assert row["order_ts_utc"] == "2026-01-01T10:00:00Z"
    assert row["order_date"] == "2026-01-01"
