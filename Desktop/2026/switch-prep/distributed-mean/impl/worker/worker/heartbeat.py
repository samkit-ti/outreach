"""The heartbeat thread — LLD §3/§5, DM-006.

Runs on its OWN connection (a worker holds exactly two: this one, and the one
T2's multi-statement transaction owns — they can never share, LLD §5). Every
extension is fenced by token AND status, and capped by ``deadline_at``: a
wedged-but-heartbeating worker cannot hold a task past its absolute deadline
because this UPDATE stops matching. The thread is STOPPED before T2 opens.
"""

from __future__ import annotations

import threading
from typing import Any

import psycopg

_HEARTBEAT_SQL = """
UPDATE tasks SET lease_expires_at = now() + make_interval(secs => %(lease_seconds)s)
WHERE id = %(task_id)s
  AND lease_token = %(lease_token)s
  AND status = 'claimed'
  AND lease_expires_at < deadline_at
"""


class Heartbeat:
    """Extend one task's lease every ``HEARTBEAT_SECONDS`` until stopped."""

    def __init__(
        self,
        conn: psycopg.Connection[Any],
        *,
        task_id: str,
        lease_token: str,
        lease_seconds: int,
        heartbeat_seconds: int,
    ) -> None:
        self._conn = conn
        self._task_id = task_id
        self._lease_token = lease_token
        self._lease_seconds = lease_seconds
        self._interval = heartbeat_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"heartbeat-{task_id[:8]}", daemon=True
        )

    def _beat_once(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                _HEARTBEAT_SQL,
                {
                    "task_id": self._task_id,
                    "lease_token": self._lease_token,
                    "lease_seconds": self._lease_seconds,
                },
            )
        self._conn.commit()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._beat_once()
            except psycopg.Error:
                # A failed beat is not a task failure: the lease simply isn't
                # extended this round. If the DB stays down the lease expires
                # and the reaper requeues — the designed degradation (DM-006).
                try:
                    self._conn.rollback()
                except psycopg.Error:
                    return  # connection is gone; the lease path takes over

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        """Block until the thread has exited. MUST be called before T2 opens."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
