"""Supervisor configuration — env-driven, fail-fast.

Every value here is quoted from LLD §8 (the single source of truth for defaults).
Nothing in this module invents a default that the design doc does not state, and
nothing silently swallows a malformed value: a bad env var raises at import time
rather than producing a plausible-but-wrong reaper cadence at 03:00.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """A required env var is missing or unparseable."""


def _req_str(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raise ConfigError(f"{name} is required and must be non-empty")
    return raw


def _int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:  # explicit: never fall back to the default on garbage
            raise ConfigError(f"{name}={raw!r} is not an integer") from exc
    if not (lo <= value <= hi):
        raise ConfigError(f"{name}={value} out of range [{lo}, {hi}]")
    return value


def _float(name: str, default: float, *, lo: float, hi: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise ConfigError(f"{name}={raw!r} is not a number") from exc
    if not (lo <= value <= hi):
        raise ConfigError(f"{name}={value} out of range [{lo}, {hi}]")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}={raw!r} is not a boolean")


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


# The env vars a newly-spawned worker container needs in order to be a worker.
# The reconciler prefers cloning an existing worker's env (authoritative); this
# list is the cold-start path when the pool is at zero and there is nothing to
# clone from.
DEFAULT_WORKER_ENV_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "S3_FORCE_PATH_STYLE",
    "INPUT_URI_ALLOWLIST",
    "K_FANIN",
    "LEASE_SECONDS",
    "HEARTBEAT_SECONDS",
    "TASK_DEADLINE_SECONDS",
    "MAX_ATTEMPTS",
    "IDLE_POLL_MS",
    "SPEED_FACTOR",
    "LOG_LEVEL",
)


@dataclass(frozen=True)
class Config:
    # --- database -----------------------------------------------------------
    database_url: str

    # --- LLD §8 tunables ----------------------------------------------------
    k_fanin: int                      # fan-in; also the pairing threshold
    reaper_seconds: int               # T3 cadence
    lease_seconds: int                # quoted for logging/diagnostics only
    task_deadline_seconds: int        # quoted for logging/diagnostics only
    finalize_max_attempts: int        # LLD §4 T3: finalize is seeded with 10

    # --- reconciler (DM-008) ------------------------------------------------
    reconciler_seconds: int
    worker_max: int                   # W_max = 32 (DM-008 / A-7)
    worker_stale_seconds: int         # workers-table prune threshold
    worker_stop_grace_seconds: int    # compose stop_grace_period / ECS StopTimeout
    docker_project: str               # compose project name (label scoping)
    docker_worker_service: str        # compose service name of the worker
    worker_role_label: str            # explicit label we own: dm.role=worker
    worker_image: str                 # cold-start template when the pool is at 0
    worker_network: str               # cold-start template network
    worker_env_keys: tuple[str, ...] = field(default=DEFAULT_WORKER_ENV_KEYS)

    # --- behaviour switches -------------------------------------------------
    reconcile_enabled: bool = True
    log_level: str = "INFO"
    stranded_event_min_interval_seconds: int = 60

    @property
    def worker_label_filter(self) -> dict[str, str]:
        """Docker label filter identifying the *scalable* worker pool.

        Two labels, both required: our own `dm.role` (so a hand-pinned straggler
        container can opt out of being scaled away, see the straggler override)
        and the compose project (so two stacks on one daemon never scale each
        other's workers).
        """
        return {
            "dm.role": self.worker_role_label,
            "com.docker.compose.project": self.docker_project,
        }


def load() -> Config:
    return Config(
        database_url=_req_str("DATABASE_URL"),
        k_fanin=_int("K_FANIN", 5, lo=2, hi=64),
        reaper_seconds=_int("REAPER_SECONDS", 5, lo=1, hi=3600),
        lease_seconds=_int("LEASE_SECONDS", 30, lo=5, hi=3600),
        task_deadline_seconds=_int("TASK_DEADLINE_SECONDS", 300, lo=10, hi=86400),
        finalize_max_attempts=_int("FINALIZE_MAX_ATTEMPTS", 10, lo=1, hi=100),
        reconciler_seconds=_int("RECONCILER_SECONDS", 5, lo=1, hi=3600),
        worker_max=_int("WORKER_MAX", 32, lo=0, hi=1024),
        worker_stale_seconds=_int("WORKER_STALE_SECONDS", 60, lo=5, hi=86400),
        worker_stop_grace_seconds=_int("WORKER_STOP_GRACE_SECONDS", 120, lo=1, hi=3600),
        docker_project=os.environ.get("DM_PROJECT", "distributed-mean").strip(),
        docker_worker_service=os.environ.get("DM_WORKER_SERVICE", "worker").strip(),
        worker_role_label=os.environ.get("DM_WORKER_ROLE_LABEL", "worker").strip(),
        worker_image=os.environ.get("WORKER_IMAGE", "distributed-mean-worker").strip(),
        worker_network=os.environ.get("WORKER_NETWORK", "distributed-mean_default").strip(),
        worker_env_keys=_csv("WORKER_ENV_KEYS", DEFAULT_WORKER_ENV_KEYS),
        reconcile_enabled=_bool("RECONCILE_ENABLED", True),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        stranded_event_min_interval_seconds=_int(
            "STRANDED_EVENT_MIN_INTERVAL_SECONDS", 60, lo=1, hi=86400
        ),
    )


# Kept so the unused-import linter cannot hide a genuinely unused knob.
__all__ = ["Config", "ConfigError", "load", "DEFAULT_WORKER_ENV_KEYS"]
