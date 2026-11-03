"""
Schema definitions, validation rules, constants, and reject reason codes.
"""

from decimal import Decimal
from typing import Final, List, Set

# Reject reason codes
MALFORMED_ROW: Final[str] = "MALFORMED_ROW"
MISSING_REQUIRED: Final[str] = "MISSING_REQUIRED"
INVALID_TYPE: Final[str] = "INVALID_TYPE"
INVALID_FORMAT: Final[str] = "INVALID_FORMAT"
INVALID_VALUE: Final[str] = "INVALID_VALUE"
FUTURE_TIMESTAMP: Final[str] = "FUTURE_TIMESTAMP"
INVALID_FK: Final[str] = "INVALID_FK"
DUPLICATE_SUPERSEDED: Final[str] = "DUPLICATE_SUPERSEDED"

# File-level failure reason codes
SCHEMA_MISSING_COLUMNS: Final[str] = "SCHEMA_MISSING_COLUMNS"
EMPTY_FILE_NO_HEADER: Final[str] = "EMPTY_FILE_NO_HEADER"
FILE_NOT_FOUND: Final[str] = "FILE_NOT_FOUND"

# Lineage & exclusion
LINEAGE_COLUMNS: Final[List[str]] = ["source_file", "run_id"]
RECON_EXCLUDE_COLUMNS: Final[Set[str]] = {"run_id", "source_file"}

# Reject file schema
REJECT_COLUMNS: Final[List[str]] = [
    "run_id",
    "source_file",
    "source_line_number",
    "entity",
    "business_key",
    "reason_code",
    "reason_detail",
    "raw_record",
]

# Source column specifications
CUSTOMERS_REQUIRED_COLUMNS: Final[List[str]] = [
    "customer_id",
    "customer_name",
    "country_code",
    "created_at",
    "updated_at",
]

CUSTOMERS_ALL_COLUMNS: Final[List[str]] = [
    "customer_id",
    "customer_name",
    "email",
    "country_code",
    "created_at",
    "updated_at",
]

ORDERS_REQUIRED_COLUMNS: Final[List[str]] = [
    "order_id",
    "customer_id",
    "order_ts",
    "status",
    "amount",
    "currency",
    "updated_at",
]

ORDERS_ALL_COLUMNS: Final[List[str]] = [
    "order_id",
    "customer_id",
    "order_ts",
    "status",
    "amount",
    "currency",
    "updated_at",
]

# Target column specifications
DIM_CUSTOMERS_COLUMNS: Final[List[str]] = [
    "customer_id",
    "customer_name",
    "email",
    "country_code",
    "created_at_utc",
    "updated_at_utc",
    "source_file",
    "run_id",
]

FACT_ORDERS_COLUMNS: Final[List[str]] = [
    "order_id",
    "customer_id",
    "order_ts_utc",
    "order_date",
    "status",
    "amount",
    "currency",
    "amount_band",
    "updated_at_utc",
    "source_file",
    "run_id",
]

# Validation rules constants
CUSTOMER_ID_REGEX: Final[str] = r"^C\d{6}$"
ORDER_ID_REGEX: Final[str] = r"^O\d{8}$"
COUNTRY_CODE_REGEX: Final[str] = r"^[A-Za-z]{2}$"

ALLOWED_STATUSES: Final[Set[str]] = {
    "created",
    "paid",
    "shipped",
    "delivered",
    "cancelled",
    "refunded",
}

ALLOWED_CURRENCIES: Final[Set[str]] = {"USD", "EUR", "INR", "GBP"}

MIN_AMOUNT: Final[Decimal] = Decimal("0.00")
MAX_AMOUNT: Final[Decimal] = Decimal("1000000.00")
