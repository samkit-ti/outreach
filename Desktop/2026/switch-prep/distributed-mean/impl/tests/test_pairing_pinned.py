"""The pinned-interleaving pairing test (LLD §10): two connections, the advisory
lock actually serialises — DB-only, no API, synthetic rows cleaned up."""

from __future__ import annotations

import threading
import time
import uuid

import pytest


LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('pairing'), hashtext(%s::text))"


@pytest.fixture
def synthetic_job(db_connect):
    """A job row two partial rows, created outside the API, removed afterwards."""
    job_id = str(uuid.uuid4())
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (id, f, c, status) VALUES (%s, 10, 4, 'running')",
            (job_id,),
        )
        for i in range(2):
            cur.execute(
                """INSERT INTO tasks (job_id, type, status, priority, payload)
                   VALUES (%s, 'map', 'done', 2, %s::jsonb) RETURNING id""",
                (job_id, f'{{"kind":"map","jobId":"{job_id}","inputUris":["s3://x/{i}.f64"],"c":4}}'),
            )
            task_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO partials (job_id, uri, count, produced_by)
                   VALUES (%s, %s, 5, %s)""",
                (job_id, f"s3://x/jobs/{job_id}/partials/{task_id}.f64", task_id),
            )
    conn.commit()
    yield job_id, conn
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM partials WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM tasks WHERE job_id = %s", (job_id,))
        cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    conn.commit()
    conn.close()


def test_advisory_lock_serialises_pairing(synthetic_job, db_connect) -> None:
    job_id, holder = synthetic_job

    # Connection 1 takes the pairing lock and holds it inside an open transaction.
    with holder.cursor() as cur:
        cur.execute(LOCK_SQL, (job_id,))

        # Connection 2 attempts the same lock on a thread; it must BLOCK.
        acquired_at: list[float] = []
        blocker = db_connect()

        def contend() -> None:
            with blocker.cursor() as cur2:
                cur2.execute(LOCK_SQL, (job_id,))
                acquired_at.append(time.monotonic())
            blocker.commit()

        thread = threading.Thread(target=contend)
        released_at = None
        thread.start()
        time.sleep(1.0)
        assert not acquired_at, "second pairing transaction acquired the lock while held"

        # Verify via pg_locks that someone is waiting on an advisory lock.
        check = db_connect()
        with check.cursor() as cur3:
            cur3.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
            )
            waiting = cur3.fetchone()[0]
        check.commit()
        check.close()
        assert waiting >= 1, "expected a blocked advisory-lock waiter in pg_locks"

        released_at = time.monotonic()
    holder.commit()  # xact lock releases here

    thread.join(timeout=10)
    blocker.close()
    assert acquired_at, "second transaction never acquired the lock after release"
    assert acquired_at[0] >= released_at, "acquired before the holder released"
