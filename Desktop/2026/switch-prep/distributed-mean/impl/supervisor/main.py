"""Supervisor entry point: reaper every REAPER_SECONDS, reconciler every
RECONCILER_SECONDS, one process, independent failure domains (an exception in
one duty never stops the other — degraded, not broken, DM-006)."""

from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType

import psycopg

from .config import Config, ConfigError, load
from .reaper import reap_once
from .reconciler import DockerReconciler

log = logging.getLogger("supervisor")


class Supervisor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.stopping = False
        self.conn = psycopg.connect(cfg.database_url, autocommit=False)
        self.reconciler: DockerReconciler | None = None
        if cfg.reconcile_enabled:
            try:
                self.reconciler = DockerReconciler(cfg)
            except Exception as exc:  # noqa: BLE001 — no docker.sock → reaper-only mode
                log.warning("reconciler disabled (docker unavailable): %s", exc)

    def _stop(self, _signum: int, _frame: FrameType | None) -> None:
        self.stopping = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        log.info(
            "supervisor up (reaper every %ds, reconciler %s)",
            self.cfg.reaper_seconds,
            "on" if self.reconciler else "off",
        )
        next_reconcile = 0.0
        while not self.stopping:
            started = time.monotonic()
            try:
                reap_once(self.conn, self.cfg)
            except psycopg.Error as exc:
                log.error("reaper pass failed (leases just expire later): %s", exc)
                try:
                    self.conn.rollback()
                except psycopg.Error:
                    self.conn = psycopg.connect(self.cfg.database_url, autocommit=False)
            if self.reconciler is not None and started >= next_reconcile:
                try:
                    self.reconciler.reconcile_once(self.conn)
                except Exception as exc:  # noqa: BLE001 — W drifts; correctness unaffected
                    log.error("reconcile pass failed (W drifts until next pass): %s", exc)
                    try:
                        self.conn.rollback()
                    except psycopg.Error:
                        pass
                next_reconcile = started + self.cfg.reconciler_seconds
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, self.cfg.reaper_seconds - elapsed))
        self.conn.close()
        log.info("supervisor stopped")


def main() -> int:
    try:
        cfg = load()
    except ConfigError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    Supervisor(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
