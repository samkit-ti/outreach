"""The claim query — LLD §3, verbatim semantics.

One statement is the whole queue: an ``inflight`` CTE for fairness (computed
fresh per claim, never a correlated subquery), a 16-row candidate window under
``FOR UPDATE SKIP LOCKED`` (a contended head must not return zero rows to W−1
claimers), and an UPDATE of the first survivor that stamps every lease and
deadline value from the DB's ``now()`` — the worker sends only durations.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from .config import WorkerConfig
from .types import ClaimedTask, parse_payload

_CLAIM_SQL = """
WITH inflight AS (
  SELECT job_id, count(*) AS n
  FROM tasks WHERE status = 'claimed' GROUP BY job_id
),
candidate AS (
  SELECT t.id
  FROM tasks t
  JOIN jobs j ON j.id = t.job_id
             AND j.status IN ('running', 'finalizing')
  LEFT JOIN inflight i ON i.job_id = t.job_id
  WHERE t.status = 'pending'
  ORDER BY COALESCE(i.n, 0), t.priority ASC, t.created_at
  LIMIT 16
  FOR UPDATE OF t SKIP LOCKED
)
UPDATE tasks SET
  status = 'claimed',
  worker_id = %(worker_id)s,
  attempts = attempts + 1,
  lease_token = gen_random_uuid(),
  claimed_at = now(),
  deadline_at = now() + make_interval(secs => %(deadline_seconds)s),
  lease_expires_at = now() + make_interval(secs => %(lease_seconds)s)
WHERE id = (SELECT id FROM candidate LIMIT 1)
RETURNING id, type, payload, lease_token, job_id
"""


def _claim_once(conn: psycopg.Connection[Any], cfg: WorkerConfig, worker_id: str) -> ClaimedTask | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            _CLAIM_SQL,
            {
                "worker_id": worker_id,
                "deadline_seconds": cfg.task_deadline_seconds,
                "lease_seconds": cfg.lease_seconds,
            },
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    task_id, task_type, payload_raw, lease_token, job_id = row
    payload = payload_raw if isinstance(payload_raw, dict) else json.loads(payload_raw)
    return ClaimedTask(
        id=str(task_id),
        type=task_type,
        payload=parse_payload(task_type, payload, k_fanin=cfg.k_fanin),
        lease_token=str(lease_token),
        job_id=str(job_id),
    )


def claim(conn: psycopg.Connection[Any], cfg: WorkerConfig, worker_id: str) -> ClaimedTask | None:
    """Claim the next task, or ``None`` after the empty-queue idle sleep.

    LLD §3's contended-head rule: an empty first attempt retries once
    immediately (the head may simply have been locked), and only then sleeps
    ``IDLE_POLL_MS`` with jitter.
    """
    task = _claim_once(conn, cfg, worker_id)
    if task is not None:
        return task
    task = _claim_once(conn, cfg, worker_id)
    if task is not None:
        return task
    time.sleep((cfg.idle_poll_ms / 1000.0) * (0.75 + random.random() * 0.5))
    return None
