"""
Resilient CSV ingestion with line numbering, malformed row quarantine, and schema drift checks.
"""

import csv
import logging
import os
from pathlib import Path
from typing import List, Sequence, Tuple
import pandas as pd

from recon.errors import FileFormatError, SchemaError
from recon.schemas import (
    EMPTY_FILE_NO_HEADER,
    FILE_NOT_FOUND,
    MALFORMED_ROW,
    REJECT_COLUMNS,
    SCHEMA_MISSING_COLUMNS,
)

logger = logging.getLogger("recon.ingest")


def ingest_csv(
    file_path: Path,
    entity: str,
    required_columns: Sequence[str],
    all_known_columns: Sequence[str],
    run_id: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Ingests a CSV file using stdlib csv reader line-by-line.

    Args:
        file_path: Path to the CSV file.
        entity: Name of the entity ("customers" or "orders").
        required_columns: Columns that MUST be present in the header.
        all_known_columns: Full expected column specification.
        run_id: Active execution run identifier.

    Returns:
        Tuple of (valid_records_df, rejects_df) where all data values are strings.

    Raises:
        FileFormatError: If file is missing or 0 bytes without header.
        SchemaError: If header is missing required columns.
    """
    if not file_path.is_file():
        raise FileFormatError(
            f"FILE_NOT_FOUND: file does not exist at {file_path}",
            reason_code=FILE_NOT_FOUND,
        )

    if os.path.getsize(file_path) == 0:
        raise FileFormatError(
            f"EMPTY_FILE_NO_HEADER: file {file_path.name} is zero bytes",
            reason_code=EMPTY_FILE_NO_HEADER,
        )

    source_file_name = file_path.name
    valid_rows: List[dict] = []
    reject_rows: List[dict] = []

    # Handle utf-8-sig to automatically strip BOM if present
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        try:
            header_row = next(reader)
        except StopIteration:
            raise FileFormatError(
                f"EMPTY_FILE_NO_HEADER: file {file_path.name} has no content",
                reason_code=EMPTY_FILE_NO_HEADER,
            )

        # Normalize header: trim whitespace
        headers = [h.strip() for h in header_row]
        header_len = len(headers)

        # Check for missing required columns
        missing_cols = [col for col in required_columns if col not in headers]
        if missing_cols:
            raise SchemaError(
                f"SCHEMA_MISSING_COLUMNS: missing required columns {missing_cols} in {source_file_name}",
                reason_code=SCHEMA_MISSING_COLUMNS,
            )

        # Check for extra/unrecognized columns (log warning and ignore extra during processing)
        extra_cols = [col for col in headers if col not in all_known_columns]
        if extra_cols:
            logger.warning(
                "Schema drift detected in %s: unrecognized columns %s will be ignored",
                source_file_name,
                extra_cols,
            )

        line_num = 1  # Header was line 1
        for row in reader:
            line_num += 1

            # Skip truly empty lines (e.g. trailing newline)
            if not row or (len(row) == 1 and row[0].strip() == ""):
                continue

            raw_line = ",".join(f'"{col}"' if "," in col else col for col in row)

            if len(row) != header_len:
                # Wrong field count -> Quarantine as MALFORMED_ROW
                business_key = row[0].strip() if row else "UNKNOWN"
                reject_rows.append(
                    {
                        "run_id": run_id,
                        "source_file": source_file_name,
                        "source_line_number": line_num,
                        "entity": entity,
                        "business_key": business_key,
                        "reason_code": MALFORMED_ROW,
                        "reason_detail": f"Expected {header_len} fields, found {len(row)}",
                        "raw_record": raw_line,
                    }
                )
                continue

            row_dict = {headers[i]: row[i] for i in range(header_len)}
            row_dict["_source_line_number"] = line_num
            row_dict["_raw_record"] = raw_line
            valid_rows.append(row_dict)

    if valid_rows:
        df = pd.DataFrame(valid_rows)
    else:
        df = pd.DataFrame(columns=list(all_known_columns) + ["_source_line_number", "_raw_record"])

    if reject_rows:
        rejects_df = pd.DataFrame(reject_rows)
    else:
        rejects_df = pd.DataFrame(columns=REJECT_COLUMNS)

    return df, rejects_df
