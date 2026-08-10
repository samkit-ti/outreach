"""T3 — the reaper (LLD §4), every REAPER_SECONDS.

Five duties, in order:
1. Requeue expired/over-deadline claimed tasks (rotating the lease token) or
   kill them once attempts are exhausted.
2. Run the eager-pairing step, under the per-job advisory lock, for every job
   whose task was touched — the reaper is a first-class pairing trigger.
3. Fail jobs holding dead tasks — EXCEPT a job that still holds an unconsumed
   count==F partial (its answer exists; emit ``job.needs_finalize`` instead).
4. Backstop sweep: jobs in running/finalizing with nothing in flight — re-pair,
   and for a ``finalizing`` job whose finalize task was lost, re-enqueue it.
5. Prune workers whose heartbeat went stale.

All time arithmetic is the DB's ``now()``; this process never sends timestamps.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from worker.commit import run_pairing  # the same pairing step T2 runs

from .config import Config

log = logging.getLogger("reaper")

_REAP = """
UPDATE tasks SET
  status = CASE WHEN attempts >= max_attempts THEN 'dead'::task_status
                ELSE 'pending'::task_status END,
  worker_id = NULL,
  lease_token = NULL,
  lease_expires_at = NULL,
  last_error = COALESCE(last_error, 'lease expired or task deadline exceeded')
WHERE status = 'claimed'
  AND (lease_expires_at < now() OR now() > deadline_at)
RETURNING id, job_id, type, status
"""

_FAIL_JOBS = """
UPDATE jobs SET status = 'failed',
                error = 'task exhausted retries: ' || d.task_ids
FROM (
  SELECT job_id, string_agg(id::text, ', ') AS task_ids
  FROM tasks WHERE status = 'dead' GROUP BY job_id
) d
WHERE jobs.id = d.job_id
  AND jobs.status IN ('running', 'finalizing')
  AND NOT EXISTS (
    SELECT 1 FROM partials p
    WHERE p.job_id = jobs.id AND p.consumed_by IS NULL AND p.count = jobs.f
  )
RETURNING jobs.id
"""

_NEEDS_FINALIZE = """
SELECT DISTINCT j.id, j.f, j.c, p.uri
FROM jobs j
JOIN tasks t ON t.job_id = j.id AND t.status = 'dead'
JOIN partials p ON p.job_id = j.id AND p.consumed_by IS NULL AND p.count = j.f
WHERE j.status IN ('running', 'finalizing')
"""

_QUIET_JOBS = """
SELECT j.id, j.status, j.f, j.c
FROM jobs j
WHERE j.status IN ('running', 'finalizing')
  AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.job_id = j.id AND t.status IN ('pending', 'claimed')
  )
"""

_ROOT_PARTIAL = """
SELECT uri FROM partials
WHERE job_id = %(job_id)s AND consumed_by IS NULL AND count = %(f)s
"""

_INSERT_FINALIZE = """
INSERT INTO tasks (job_id, type, status, priority, payload, max_attempts)
VALUES (%(job_id)s, 'finalize', 'pending', 0, %(payload)s, %(max_attempts)s)
"""

_PRUNE_WORKERS = """
DELETE FROM workers
WHERE last_heartbeat < now() - make_interval(secs => %(stale)s)
RETURNING id
"""

_EVENT = """
INSERT INTO events (type, job_id, task_id, worker_id, payload)
VALUES (%(type)s, %(job_id)s, %(task_id)s, %(worker_id)s, %(payload)s)
"""


def _emit(cur: psycopg.Cursor[Any], type_: str, **kw: Any) -> None:
    cur.execute(
        _EVENT,
        {
            "type": type_,
            "job_id": kw.get("job_id"),
            "task_id": kw.get("task_id"),
            "worker_id": kw.get("worker_id"),
            "payload": json.dumps(kw.get("payload", {})),
        },
    )


def reap_once(conn: psycopg.Connection[Any], cfg: Config) -> None:
    touched_jobs: set[str] = set()

    # 1. Requeue / kill expired holders.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(_REAP)
        for task_id, job_id, task_type, new_status in cur.fetchall():
            touched_jobs.add(str(job_id))
            _emit(
                cur,
                "task.lease_expired" if new_status == "pending" else "task.dead",
                job_id=job_id,
                task_id=task_id,
                payload={"type": task_type, "requeued": new_status == "pending"},
            )
            log.warning("reaped %s task %s (job %s) -> %s", task_type, task_id, job_id, new_status)

    # 2. Pairing for every touched job — its own short transaction per job so a
    #    contended advisory lock never blocks the whole pass.
    for job_id in touched_jobs:
        with conn.transaction(), conn.cursor() as cur:
            run_pairing(cur, job_id=job_id, k_fanin=cfg.k_fanin)

    # 3. Fail jobs with dead tasks — unless the answer already exists.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(_NEEDS_FINALIZE)
        for job_id, _f, _c, _uri in cur.fetchall():
            _emit(cur, "job.needs_finalize", job_id=job_id)
        cur.execute(_FAIL_JOBS)
        for (job_id,) in cur.fetchall():
            _emit(cur, "job.failed", job_id=job_id)
            log.error("job %s FAILED (dead task, no completed answer)", job_id)

    # 4. Backstop sweep — under the pairing exhaustive-trigger set this finds
    #    nothing; anything here is logged loudly as instrumentation.
    with conn.cursor() as cur_ro:
        cur_ro.execute(_QUIET_JOBS)
        quiet = cur_ro.fetchall()
    conn.commit()
    for job_id, status, f, c in quiet:
        with conn.transaction(), conn.cursor() as cur:
            if status == "running":
                run_pairing(cur, job_id=str(job_id), k_fanin=cfg.k_fanin)
            else:  # finalizing with no finalize task in flight: re-enqueue it
                cur.execute(_ROOT_PARTIAL, {"job_id": job_id, "f": f})
                row = cur.fetchone()
                if row is not None:
                    payload = {
                        "kind": "finalize",
                        "jobId": str(job_id),
                        "partialUri": row[0],
                        "f": f,
                        "c": c,
                    }
                    cur.execute(
                        _INSERT_FINALIZE,
                        {
                            "job_id": job_id,
                            "payload": json.dumps(payload),
                            "max_attempts": cfg.finalize_max_attempts,
                        },
                    )
                    log.warning("backstop re-enqueued finalize for job %s", job_id)

    # 5. Stale workers.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(_PRUNE_WORKERS, {"stale": cfg.worker_stale_seconds})
        for (worker_id,) in cur.fetchall():
            _emit(cur, "worker.gone", worker_id=worker_id)
            log.warning("pruned stale worker %s", worker_id)
