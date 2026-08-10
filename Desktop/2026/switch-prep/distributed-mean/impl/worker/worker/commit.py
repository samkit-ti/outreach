"""T2 — task completion + eager pairing, one transaction (LLD §4).

Order inside the transaction is load-bearing:

1. Fenced task-update (``lease_token`` + ``status='claimed'``). 0 rows → the
   lease was reaped and the task reassigned → ROLLBACK and discard; the PUT the
   executor already did is harmless (deterministic key, byte-identical bytes).
2. For map/reduce: insert the partial (``ON CONFLICT (produced_by) DO NOTHING``
   — a redelivery cannot record the same sums twice).
3. The pairing step, ALWAYS (whether or not the insert returned a row — the
   skip-on-conflict shortcut is exactly what re-opens the stranding hole),
   serialised per job by ``pg_advisory_xact_lock('pairing', job_id)``.
4. For finalize: the ``finalizing → completed`` CAS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from .types import (
    PRIORITY_BY_TYPE,
    ClaimedTask,
    FinalizePayload,
    MapPayload,
    ReducePayload,
    TaskResult,
)

_FINALIZE_MAX_ATTEMPTS = 10  # LLD §8: one idempotent 8 MB read + a divide

_FENCED_DONE = """
UPDATE tasks SET status = 'done', finished_at = now()
WHERE id = %(task_id)s AND lease_token = %(lease_token)s AND status = 'claimed'
"""

_INSERT_PARTIAL = """
INSERT INTO partials (job_id, uri, count, produced_by)
VALUES (%(job_id)s, %(uri)s, %(count)s, %(task_id)s)
ON CONFLICT (produced_by) DO NOTHING
"""

_ADVISORY_LOCK = "SELECT pg_advisory_xact_lock(hashtext('pairing'), hashtext(%(job_id)s::text))"

_UNCONSUMED = """
SELECT id, uri, count FROM partials
WHERE job_id = %(job_id)s AND consumed_by IS NULL
ORDER BY created_at
FOR UPDATE
"""

_IN_FLIGHT = """
SELECT count(*) FROM tasks
WHERE job_id = %(job_id)s AND status IN ('pending', 'claimed')
"""

_REDUCE_COUNT = "SELECT COALESCE(sum(count), 0) FROM partials WHERE consumed_by = %(task_id)s"

_INSERT_TASK = """
INSERT INTO tasks (job_id, type, status, priority, payload, max_attempts)
VALUES (%(job_id)s, %(type)s, 'pending', %(priority)s, %(payload)s, %(max_attempts)s)
RETURNING id
"""

_CONSUME = "UPDATE partials SET consumed_by = %(reduce_id)s WHERE id = ANY(%(ids)s)"

_CAS_FINALIZING = """
UPDATE jobs SET status = 'finalizing' WHERE id = %(job_id)s AND status = 'running'
"""

_CAS_COMPLETED = """
UPDATE jobs SET status = 'completed', result_uri = %(uri)s, completed_at = now()
WHERE id = %(job_id)s AND status = 'finalizing'
"""

_INSERT_EVENT = """
INSERT INTO events (type, job_id, task_id, worker_id, payload)
VALUES (%(type)s, %(job_id)s, %(task_id)s, %(worker_id)s, %(payload)s)
"""


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    committed: bool  # False → fence failed: lease reaped, work discarded
    job_completed: bool


def _event(
    cur: psycopg.Cursor[Any],
    *,
    type_: str,
    job_id: str,
    task_id: str | None = None,
    worker_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        _INSERT_EVENT,
        {
            "type": type_,
            "job_id": job_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "payload": json.dumps(payload or {}),
        },
    )


def run_pairing(cur: psycopg.Cursor[Any], *, job_id: str, k_fanin: int) -> bool:
    """The eager-pairing step (LLD §4). Caller must already be inside a
    transaction. Returns True if it enqueued the finalize task.

    Called from T2 (every successful fenced commit) and from the reaper's T3
    (every job whose task it touches) — together the exhaustive trigger set.
    """
    cur.execute(_ADVISORY_LOCK, {"job_id": job_id})

    cur.execute("SELECT status, f, c FROM jobs WHERE id = %(job_id)s", {"job_id": job_id})
    job_row = cur.fetchone()
    if job_row is None:
        return False
    job_status, job_f, job_c = job_row
    if job_status != "running":
        return False  # finalizing/completed/failed: nothing left to pair

    while True:
        cur.execute(_UNCONSUMED, {"job_id": job_id})
        partials = cur.fetchall()

        if len(partials) >= k_fanin:
            take = partials[:k_fanin]
        else:
            cur.execute(_IN_FLIGHT, {"job_id": job_id})
            in_flight = cur.fetchone()[0]
            if len(partials) == 1 and partials[0][2] == job_f and in_flight == 0:
                cur.execute(_CAS_FINALIZING, {"job_id": job_id})
                if cur.rowcount != 1:
                    return False  # someone else finalized: no-op
                payload = {
                    "kind": "finalize",
                    "jobId": job_id,
                    "partialUri": partials[0][1],
                    "f": job_f,
                    "c": job_c,
                }
                cur.execute(
                    _INSERT_TASK,
                    {
                        "job_id": job_id,
                        "type": "finalize",
                        "priority": PRIORITY_BY_TYPE["finalize"],
                        "payload": json.dumps(payload),
                        "max_attempts": _FINALIZE_MAX_ATTEMPTS,
                    },
                )
                return True
            if len(partials) >= 2 and in_flight == 0:
                take = partials  # drain mode: fan-in 2–4
            else:
                if in_flight == 0 and partials:
                    # Unreachable under the conservation invariant; if a bug
                    # ever breaks the partition, this is the detector (LLD §4).
                    _event(
                        cur,
                        type_="job.stranded",
                        job_id=job_id,
                        payload={"partials": [str(p[0]) for p in partials]},
                    )
                return False

        payload = {
            "kind": "reduce",
            "jobId": job_id,
            "partialIds": [str(p[0]) for p in take],
            "partialUris": [p[1] for p in take],
            "c": job_c,
        }
        cur.execute(
            _INSERT_TASK,
            {
                "job_id": job_id,
                "type": "reduce",
                "priority": PRIORITY_BY_TYPE["reduce"],
                "payload": json.dumps(payload),
                "max_attempts": 3,
            },
        )
        reduce_id = cur.fetchone()[0]
        cur.execute(_CONSUME, {"reduce_id": reduce_id, "ids": [p[0] for p in take]})
        # Loop: more than 2×K partials may be ready (e.g. after a reaper pass).


def commit_done(
    conn: psycopg.Connection[Any],
    task: ClaimedTask,
    result: TaskResult,
    *,
    worker_id: str,
    k_fanin: int,
) -> CommitOutcome:
    """T2. The executor has already PUT ``result.output_uri``."""
    payload = task.payload
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(_FENCED_DONE, {"task_id": task.id, "lease_token": task.lease_token})
            if cur.rowcount != 1:
                # Zombie: our lease was reaped while we worked. Nothing to undo —
                # the transaction context manager rolls back on raise, but here we
                # simply record nothing and leave the PUT (byte-identical) behind.
                raise _FenceLost()

            job_completed = False
            if isinstance(payload, (MapPayload, ReducePayload)):
                if isinstance(payload, MapPayload):
                    count = result.count
                else:
                    cur.execute(_REDUCE_COUNT, {"task_id": task.id})
                    count = int(cur.fetchone()[0])
                cur.execute(
                    _INSERT_PARTIAL,
                    {
                        "job_id": task.job_id,
                        "uri": result.output_uri,
                        "count": count,
                        "task_id": task.id,
                    },
                )
                _event(
                    cur,
                    type_="task.done",
                    job_id=task.job_id,
                    task_id=task.id,
                    worker_id=worker_id,
                    payload={"type": payload.kind, "count": count},
                )
                run_pairing(cur, job_id=task.job_id, k_fanin=k_fanin)
            elif isinstance(payload, FinalizePayload):
                cur.execute(
                    _CAS_COMPLETED, {"job_id": task.job_id, "uri": result.output_uri}
                )
                job_completed = cur.rowcount == 1
                _event(
                    cur,
                    type_="task.done",
                    job_id=task.job_id,
                    task_id=task.id,
                    worker_id=worker_id,
                    payload={"type": "finalize"},
                )
                if job_completed:
                    _event(
                        cur,
                        type_="job.completed",
                        job_id=task.job_id,
                        payload={"resultUri": result.output_uri},
                    )
    return CommitOutcome(committed=True, job_completed=job_completed)


class _FenceLost(Exception):
    """Internal: the fenced update matched 0 rows."""


def commit_done_or_discard(
    conn: psycopg.Connection[Any],
    task: ClaimedTask,
    result: TaskResult,
    *,
    worker_id: str,
    k_fanin: int,
) -> CommitOutcome:
    try:
        return commit_done(conn, task, result, worker_id=worker_id, k_fanin=k_fanin)
    except _FenceLost:
        return CommitOutcome(committed=False, job_completed=False)
