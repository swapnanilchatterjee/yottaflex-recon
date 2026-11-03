"""
Unit tests for resilient CSV ingestion.
"""

from pathlib import Path
import pytest
import pandas as pd

from recon.errors import FileFormatError, SchemaError
from recon.ingest import ingest_csv
from recon.schemas import (
    CUSTOMERS_ALL_COLUMNS,
    CUSTOMERS_REQUIRED_COLUMNS,
    EMPTY_FILE_NO_HEADER,
    FILE_NOT_FOUND,
    MALFORMED_ROW,
    SCHEMA_MISSING_COLUMNS,
)


def test_zero_byte_file(tmp_path: Path):
    empty_file = tmp_path / "zero.csv"
    empty_file.write_text("", encoding="utf-8")

    with pytest.raises(FileFormatError) as exc_info:
        ingest_csv(empty_file, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "r1")

    assert exc_info.value.reason_code == EMPTY_FILE_NO_HEADER


def test_missing_file_raises_not_found(tmp_path: Path):
    missing_file = tmp_path / "non_existent.csv"
    with pytest.raises(FileFormatError) as exc_info:
        ingest_csv(missing_file, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "r1")

    assert exc_info.value.reason_code == FILE_NOT_FOUND


def test_missing_column_fails_with_schema_error(tmp_path: Path):
    bad_header_file = tmp_path / "bad_header.csv"
    bad_header_file.write_text("customer_id,customer_name\nC000001,Alice\n", encoding="utf-8")

    with pytest.raises(SchemaError) as exc_info:
        ingest_csv(bad_header_file, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "r1")

    assert exc_info.value.reason_code == SCHEMA_MISSING_COLUMNS


def test_extra_column_ignored_with_warning(tmp_path: Path, caplog):
    extra_col_file = tmp_path / "extra_col.csv"
    content = "customer_id,customer_name,email,country_code,created_at,updated_at,unrecognized_flag\n"
    content += "C000001,Alice,alice@example.com,US,2026-01-01T10:00:00Z,2026-01-01T12:00:00Z,extra_val\n"
    extra_col_file.write_text(content, encoding="utf-8")

    df, rejects = ingest_csv(extra_col_file, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_ALL_COLUMNS, "r1")
    assert len(df) == 1
    assert len(rejects) == 0
    assert "unrecognized_flag" in caplog.text


def test_malformed_row_quarantined(tmp_path: Path):
    file_path = tmp_path / "malformed.csv"
    content = "customer_id,customer_name,country_code,created_at,updated_at\n"
    content += "C000001,Alice,US,2026-01-01T10:00:00Z,2026-01-01T12:00:00Z\n"
    content += "C000002,Bob,DE,too_few_fields\n"  # line 3: only 4 fields instead of 5
    content += "C000003,Charlie,FR,2026-01-01T10:00:00Z,2026-01-01T12:00:00Z,EXTRA,EXTRA2\n"  # line 4: 7 fields
    content += "C000004,David,IN,2026-01-01T10:00:00Z,2026-01-01T12:00:00Z\n"
    file_path.write_text(content, encoding="utf-8")

    df, rejects = ingest_csv(file_path, "customers", CUSTOMERS_REQUIRED_COLUMNS, CUSTOMERS_REQUIRED_COLUMNS, "r1")

    assert len(df) == 2
    assert len(rejects) == 2
    assert set(rejects["reason_code"]) == {MALFORMED_ROW}
    assert list(rejects["source_line_number"]) == [3, 4]
    assert rejects.iloc[0]["business_key"] == "C000002"
