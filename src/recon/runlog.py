"""
Deterministic run identification, execution telemetry, run manifest, and structured logging.
"""

import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from recon import PIPELINE_VERSION


def compute_run_id(paths: Sequence[Path], pipeline_version: str = PIPELINE_VERSION) -> str:
    """Computes a deterministic run_id from the SHA-256 hash of all input file bytes and pipeline version.

    Ensures that identical input data produces the exact same run identifier across runs.
    """
    hasher = hashlib.sha256()
    hasher.update(pipeline_version.encode("utf-8"))

    # Sort paths for stable hashing order
    sorted_paths = sorted(paths, key=lambda p: str(p.name))
    for path in sorted_paths:
        if path.is_file():
            hasher.update(path.name.encode("utf-8"))
            hasher.update(path.read_bytes())
        else:
            hasher.update(path.name.encode("utf-8"))
            hasher.update(b"EMPTY_OR_NON_EXISTENT")

    digest = hasher.hexdigest()[:12]
    return f"run_{digest}"


class RunIdFilter(logging.Filter):
    """Custom logging filter to inject run_id into log records."""

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


def setup_logger(run_id: str, log_level: str = "INFO", log_file: Optional[Path] = None) -> logging.Logger:
    """Configures root/package logger with run_id in the log format."""
    logger = logging.getLogger("recon")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [run_id:%(run_id)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RunIdFilter(run_id))
    logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RunIdFilter(run_id))
        logger.addHandler(file_handler)

    return logger


class RunContext:
    """Context manager tracking execution lifecycle, metrics, and persisting run_manifest.json and run_log.jsonl."""

    def __init__(
        self,
        command: str,
        run_id: str,
        out_dir: Path,
        pipeline_version: str = PIPELINE_VERSION,
    ):
        self.command = command
        self.run_id = run_id
        self.out_dir = out_dir
        self.pipeline_version = pipeline_version
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.start_time: float = 0.0
        self.duration_seconds: float = 0.0
        self.status: str = "PENDING"
        self.failure_reason: Optional[str] = None
        self.input_counts: Dict[str, int] = {}
        self.output_counts: Dict[str, int] = {}
        self.rejected_count: int = 0
        self.attempt: int = 1

    def __enter__(self) -> "RunContext":
        self.started_at = datetime.now(timezone.utc)
        self.start_time = time.perf_counter()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = self.out_dir / "run_manifest.json"
        if manifest_path.is_file():
            try:
                prior = json.loads(manifest_path.read_text(encoding="utf-8"))
                if prior.get("run_id") == self.run_id:
                    self.attempt = prior.get("attempt", 1) + 1
            except Exception:
                self.attempt = 1

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.ended_at = datetime.now(timezone.utc)
        self.duration_seconds = round(time.perf_counter() - self.start_time, 4)

        if exc_type is not None:
            self.status = "FAILED"
            self.failure_reason = getattr(exc_val, "reason_code", str(exc_val))
        elif self.status == "PENDING":
            # If input count was 0 and output 0, mark SUCCESS_EMPTY
            total_inputs = sum(self.input_counts.values()) if self.input_counts else 0
            if total_inputs == 0 and "reconcile" not in self.command and not self.failure_reason:
                self.status = "SUCCESS_EMPTY"
            else:
                self.status = "SUCCESS"

        self._persist_manifest()
        self._append_run_log()

        # Do not suppress exceptions
        return False

    def _to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "command": self.command,
            "attempt": self.attempt,
            "pipeline_version": self.pipeline_version,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "input_counts": self.input_counts,
            "output_counts": self.output_counts,
            "rejected_count": self.rejected_count,
            "failure_reason": self.failure_reason,
        }

    def _persist_manifest(self) -> None:
        manifest_path = self.out_dir / "run_manifest.json"
        temp_fd, temp_path = tempfile.mkstemp(dir=str(self.out_dir), prefix="manifest_", suffix=".tmp")
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self._to_dict(), f, indent=2)
            os.replace(temp_path, manifest_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _append_run_log(self) -> None:
        log_path = self.out_dir / "run_log.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self._to_dict()) + "\n")
