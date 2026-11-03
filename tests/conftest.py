"""
Pytest fixtures and helper factories for reconciliation tests.
"""

from datetime import datetime, timezone
from pathlib import Path
import pytest
import pandas as pd

from recon.config import PipelineConfig, ReconConfig


@pytest.fixture
def sample_customer_record():
    return {
        "customer_id": "C000001",
        "customer_name": "Alice Smith",
        "email": "alice@example.com",
        "country_code": "US",
        "created_at": "2026-01-01T10:00:00Z",
        "updated_at": "2026-01-01T12:00:00Z",
    }


@pytest.fixture
def sample_order_record():
    return {
        "order_id": "O00000001",
        "customer_id": "C000001",
        "order_ts": "2026-01-02T14:30:00Z",
        "status": "paid",
        "amount": "149.99",
        "currency": "USD",
        "updated_at": "2026-01-02T14:35:00Z",
    }


@pytest.fixture
def fixed_now_utc():
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def pipeline_config(tmp_path, fixed_now_utc):
    return PipelineConfig(
        source_dir=tmp_path / "source",
        target_dir=tmp_path / "target",
        out_dir=tmp_path / "out",
        amount_tolerance=0.005,
        now_utc=fixed_now_utc,
    )
