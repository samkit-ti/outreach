"""T4 — executor failure, fenced identically to T2 (LLD §4).

Requeue IS the retry: attempts was incremented at claim time, so the CASE reads
the already-charged value. ``last_error`` records the cause (including the
offending URI, when the executor raised a ``PermanentInputError``).
"""

from __future__ import annotations

from typing import Any

import psycopg

_T4 = """
UPDATE tasks SET
  status = CASE WHEN attempts >= max_attempts THEN 'dead'::task_status
                ELSE 'pending'::task_status END,
  worker_id = NULL,
  lease_token = NULL,
  lease_expires_at = NULL,
  last_error = %(error)s
WHERE id = %(task_id)s AND lease_token = %(lease_token)s AND status = 'claimed'
RETURNING status
"""


def fail_task(
    conn: psycopg.Connection[Any],
    *,
    task_id: str,
    lease_token: str,
    error: BaseException,
) -> str | None:
    """Requeue (or kill) the worker's own task. Returns the new status, or
    ``None`` if the fence didn't match (lease already reaped — nothing to do)."""
    message = f"{type(error).__name__}: {error}"[:2000]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                _T4,
                {"task_id": task_id, "lease_token": lease_token, "error": message},
            )
            row = cur.fetchone()
    return None if row is None else str(row[0])
