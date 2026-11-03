"""
Unit tests for data validation, duplicate handling, FK referential integrity, and reject quarantine.
"""

from datetime import datetime, timezone
import pytest
import pandas as pd

from recon.config import PipelineConfig
from recon.schemas import (
    DUPLICATE_SUPERSEDED,
    FUTURE_TIMESTAMP,
    INVALID_FK,
    INVALID_FORMAT,
    INVALID_VALUE,
    MISSING_REQUIRED,
)
from recon.validate import validate_customers, validate_orders


def test_row_conservation(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "rec1",
            },
            {
                "customer_id": "BAD_KEY",
                "customer_name": "Bob",
                "email": "",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 3,
                "_raw_record": "rec2",
            },
            {
                "customer_id": "C000002",
                "customer_name": "",  # missing required
                "email": "",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 4,
                "_raw_record": "rec3",
            },
        ]
    )

    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(df) == len(valid) + len(rejects)
    assert len(valid) == 1
    assert len(rejects) == 2


def test_missing_required(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw",
            }
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == MISSING_REQUIRED


def test_null_email_allowed(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": None,
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw",
            }
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 1
    assert len(rejects) == 0


def test_duplicate_keeps_latest(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice V1",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",  # older
                "_source_line_number": 2,
                "_raw_record": "v1",
            },
            {
                "customer_id": "C000001",
                "customer_name": "Alice V2",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T14:00:00Z",  # newer
                "_source_line_number": 3,
                "_raw_record": "v2",
            },
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 1
    assert valid.iloc[0]["customer_name"] == "Alice V2"
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == DUPLICATE_SUPERSEDED


def test_exact_duplicate(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "row1",
            },
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 3,
                "_raw_record": "row2",
            },
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 1
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == DUPLICATE_SUPERSEDED


def test_out_of_order_duplicates(pipeline_config):
    # Newer record appears first in file, older appears second
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice Newer",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T16:00:00Z",  # newer
                "_source_line_number": 2,
                "_raw_record": "v_newer",
            },
            {
                "customer_id": "C000001",
                "customer_name": "Alice Older",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T11:00:00Z",  # older
                "_source_line_number": 3,
                "_raw_record": "v_older",
            },
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 1
    assert valid.iloc[0]["customer_name"] == "Alice Newer"
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == DUPLICATE_SUPERSEDED


def test_orphan_customer_rejected(pipeline_config):
    valid_customers = {"C000001"}
    df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C999999",  # orphan
                "order_ts": "2026-01-01T10:00:00Z",
                "status": "paid",
                "amount": "50.00",
                "currency": "USD",
                "updated_at": "2026-01-01T10:05:00Z",
                "_source_line_number": 2,
                "_raw_record": "rec",
            }
        ]
    )
    valid, rejects = validate_orders(df, valid_customers, "run1", "orders.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == INVALID_FK


def test_future_timestamp_rejected(pipeline_config):
    # pipeline_config now_utc is 2026-06-01T12:00:00Z
    valid_customers = {"C000001"}
    df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "order_ts": "2026-07-01T10:00:00Z",  # future
                "status": "paid",
                "amount": "50.00",
                "currency": "USD",
                "updated_at": "2026-07-01T10:05:00Z",
                "_source_line_number": 2,
                "_raw_record": "rec",
            }
        ]
    )
    valid, rejects = validate_orders(df, valid_customers, "run1", "orders.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == FUTURE_TIMESTAMP



def test_invalid_customer_id_format(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "123456",  # missing prefix C
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw",
            }
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == INVALID_FORMAT


def test_invalid_country_code_format(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "USA",  # 3 chars instead of 2
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw",
            }
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == INVALID_FORMAT


def test_updated_at_earlier_than_created_at_rejected(pipeline_config):
    df = pd.DataFrame(
        [
            {
                "customer_id": "C000001",
                "customer_name": "Alice",
                "email": "a@ex.com",
                "country_code": "US",
                "created_at": "2026-01-02T10:00:00Z",
                "updated_at": "2026-01-01T10:00:00Z",  # earlier
                "_source_line_number": 2,
                "_raw_record": "raw",
            }
        ]
    )
    valid, rejects = validate_customers(df, "run1", "customers.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 1
    assert rejects.iloc[0]["reason_code"] == INVALID_VALUE


def test_amount_out_of_range_rejected(pipeline_config):
    valid_customers = {"C000001"}
    df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "order_ts": "2026-01-01T10:00:00Z",
                "status": "paid",
                "amount": "-0.01",  # negative
                "currency": "USD",
                "updated_at": "2026-01-01T10:05:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw1",
            },
            {
                "order_id": "O00000002",
                "customer_id": "C000001",
                "order_ts": "2026-01-01T10:00:00Z",
                "status": "paid",
                "amount": "1000001.00",  # exceeds max 1,000,000.00
                "currency": "USD",
                "updated_at": "2026-01-01T10:05:00Z",
                "_source_line_number": 3,
                "_raw_record": "raw2",
            },
        ]
    )
    valid, rejects = validate_orders(df, valid_customers, "run1", "orders.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 2
    assert all(r == INVALID_VALUE for r in rejects["reason_code"])


def test_invalid_status_and_currency_rejected(pipeline_config):
    valid_customers = {"C000001"}
    df = pd.DataFrame(
        [
            {
                "order_id": "O00000001",
                "customer_id": "C000001",
                "order_ts": "2026-01-01T10:00:00Z",
                "status": "in_transit",  # invalid status
                "amount": "50.00",
                "currency": "USD",
                "updated_at": "2026-01-01T10:05:00Z",
                "_source_line_number": 2,
                "_raw_record": "raw1",
            },
            {
                "order_id": "O00000002",
                "customer_id": "C000001",
                "order_ts": "2026-01-01T10:00:00Z",
                "status": "paid",
                "amount": "50.00",
                "currency": "CAD",  # invalid currency
                "updated_at": "2026-01-01T10:05:00Z",
                "_source_line_number": 3,
                "_raw_record": "raw2",
            },
        ]
    )
    valid, rejects = validate_orders(df, valid_customers, "run1", "orders.csv", pipeline_config)
    assert len(valid) == 0
    assert len(rejects) == 2
    assert all(r == INVALID_VALUE for r in rejects["reason_code"])
