"""
Custom exception hierarchy for the reconciliation and ingestion pipeline.
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    def __init__(self, message: str, reason_code: str = "PIPELINE_ERROR"):
        super().__init__(message)
        self.reason_code = reason_code


class SchemaError(PipelineError):
    """Raised when source or target dataset fails structural schema expectations (e.g. missing columns)."""

    def __init__(self, message: str, reason_code: str = "SCHEMA_MISSING_COLUMNS"):
        super().__init__(message, reason_code=reason_code)


class FileFormatError(PipelineError):
    """Raised when a file cannot be read, is empty without headers, or malformed at the file level."""

    def __init__(self, message: str, reason_code: str = "EMPTY_FILE_NO_HEADER"):
        super().__init__(message, reason_code=reason_code)


class ValidationError(PipelineError):
    """Raised when validation invariants are violated."""

    def __init__(self, message: str, reason_code: str = "VALIDATION_FAILED"):
        super().__init__(message, reason_code=reason_code)
