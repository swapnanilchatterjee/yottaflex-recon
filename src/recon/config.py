"""
Configuration dataclasses for ingestion, transformation, and reconciliation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set
from recon.schemas import ALLOWED_CURRENCIES, ALLOWED_STATUSES


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration parameters for pipeline ingestion, validation, and publishing."""

    source_dir: Path
    target_dir: Path
    out_dir: Path
    amount_tolerance: float = 0.005
    max_amount: float = 1_000_000.0
    allowed_statuses: Set[str] = field(default_factory=lambda: set(ALLOWED_STATUSES))
    allowed_currencies: Set[str] = field(default_factory=lambda: set(ALLOWED_CURRENCIES))
    now_utc: Optional[datetime] = None

    def get_current_time(self) -> datetime:
        """Returns injected now_utc or current UTC time for future-timestamp validation."""
        if self.now_utc is not None:
            if self.now_utc.tzinfo is None:
                return self.now_utc.replace(tzinfo=timezone.utc)
            return self.now_utc.astimezone(timezone.utc)
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReconConfig:
    """Configuration parameters for source-to-target reconciliation checks."""

    source_dir: Path
    target_dir: Path
    out_dir: Path
    amount_tolerance: float = 0.005
    now_utc: Optional[datetime] = None
