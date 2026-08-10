"""Worker configuration — LLD §8, read once at process start.

Two rules this module exists to enforce:

1. **No silent defaults for anything that identifies a resource.** The DB URL,
   the S3 endpoint, the credentials, the bucket, and the read allow-list have no
   fallback: a worker that guesses its endpoint is a worker that silently reads
   the wrong data. Missing → ``ConfigError`` → the process refuses to start.
   The *tunables* in LLD §8 do have documented defaults, because a wrong value
   there degrades throughput rather than correctness.

2. **Nothing here is a clock reading.** ``LEASE_SECONDS`` and
   ``TASK_DEADLINE_SECONDS`` are durations handed to Postgres as
   ``make_interval(secs => …)``; the worker never sends a timestamp (LLD §3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from .errors import ConfigError

DEFAULT_K_FANIN: Final[int] = 5
DEFAULT_LEASE_SECONDS: Final[int] = 30
DEFAULT_HEARTBEAT_SECONDS: Final[int] = 10
DEFAULT_TASK_DEADLINE_SECONDS: Final[int] = 300
DEFAULT_MAX_ATTEMPTS: Final[int] = 3
DEFAULT_IDLE_POLL_MS: Final[int] = 500
DEFAULT_SPEED_FACTOR: Final[float] = 1.0
DEFAULT_BLOB_CONNECT_TIMEOUT_S: Final[int] = 5
DEFAULT_BLOB_READ_TIMEOUT_S: Final[int] = 30
DEFAULT_BLOB_MAX_ATTEMPTS: Final[int] = 3


def _require(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raise ConfigError(
            f"{name} is required and has no default; "
            "a worker that guesses this value reads or writes the wrong data"
        )
    return raw.strip()


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a float, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


def parse_allowlist(raw: str) -> tuple[str, ...]:
    """Parse ``INPUT_URI_ALLOWLIST`` into normalised ``s3://bucket/prefix`` entries.

    Comma- or whitespace-separated. Every entry must be an ``s3://`` URI with a
    non-empty bucket; anything else is a config error rather than an entry that
    silently matches nothing.
    """
    entries: list[str] = []
    for chunk in raw.replace(",", " ").split():
        candidate = chunk.strip()
        if not candidate:
            continue
        if not candidate.startswith("s3://"):
            raise ConfigError(
                f"INPUT_URI_ALLOWLIST entries must start with 's3://', got {candidate!r}"
            )
        remainder = candidate[len("s3://") :]
        if not remainder or remainder.startswith("/"):
            raise ConfigError(
                f"INPUT_URI_ALLOWLIST entry {candidate!r} names no bucket"
            )
        entries.append(candidate)
    if not entries:
        raise ConfigError("INPUT_URI_ALLOWLIST must contain at least one s3:// prefix")
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Immutable snapshot of LLD §8 for one worker process."""

    database_url: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_force_path_style: bool
    s3_region: str
    input_uri_allowlist: tuple[str, ...]
    k_fanin: int
    lease_seconds: int
    heartbeat_seconds: int
    task_deadline_seconds: int
    max_attempts: int
    idle_poll_ms: int
    speed_factor: float
    blob_connect_timeout_s: int
    blob_read_timeout_s: int
    blob_max_attempts: int

    def __post_init__(self) -> None:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ConfigError(
                "HEARTBEAT_SECONDS must be < LEASE_SECONDS or a lease expires "
                f"between beats (got {self.heartbeat_seconds} >= {self.lease_seconds})"
            )
        if self.lease_seconds > self.task_deadline_seconds:
            raise ConfigError(
                "LEASE_SECONDS must be <= TASK_DEADLINE_SECONDS: the heartbeat's "
                "'lease_expires_at < deadline_at' conjunct would never hold "
                f"(got {self.lease_seconds} > {self.task_deadline_seconds})"
            )


def load_config() -> WorkerConfig:
    """Read LLD §8 from the environment. Raises ``ConfigError`` on any problem."""
    return WorkerConfig(
        database_url=_require("DATABASE_URL"),
        s3_endpoint=_require("S3_ENDPOINT"),
        s3_access_key=_require("S3_ACCESS_KEY"),
        s3_secret_key=_require("S3_SECRET_KEY"),
        s3_bucket=_require("S3_BUCKET"),
        s3_force_path_style=_bool_env("S3_FORCE_PATH_STYLE", True),
        s3_region=os.environ.get("S3_REGION", "us-east-1").strip() or "us-east-1",
        input_uri_allowlist=parse_allowlist(_require("INPUT_URI_ALLOWLIST")),
        k_fanin=_int_env("K_FANIN", DEFAULT_K_FANIN, minimum=2),
        lease_seconds=_int_env("LEASE_SECONDS", DEFAULT_LEASE_SECONDS, minimum=1),
        heartbeat_seconds=_int_env(
            "HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS, minimum=1
        ),
        task_deadline_seconds=_int_env(
            "TASK_DEADLINE_SECONDS", DEFAULT_TASK_DEADLINE_SECONDS, minimum=1
        ),
        max_attempts=_int_env("MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, minimum=1),
        idle_poll_ms=_int_env("IDLE_POLL_MS", DEFAULT_IDLE_POLL_MS, minimum=1),
        speed_factor=_float_env("SPEED_FACTOR", DEFAULT_SPEED_FACTOR, minimum=1.0),
        blob_connect_timeout_s=_int_env(
            "BLOB_CONNECT_TIMEOUT_S", DEFAULT_BLOB_CONNECT_TIMEOUT_S, minimum=1
        ),
        blob_read_timeout_s=_int_env(
            "BLOB_READ_TIMEOUT_S", DEFAULT_BLOB_READ_TIMEOUT_S, minimum=1
        ),
        blob_max_attempts=_int_env(
            "BLOB_MAX_ATTEMPTS", DEFAULT_BLOB_MAX_ATTEMPTS, minimum=1
        ),
    )
