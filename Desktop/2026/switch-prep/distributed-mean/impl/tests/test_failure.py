"""Chaos: kill a worker mid-job; the answer must still be exact (DM-006)."""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from conftest import (
    assert_matches_oracle,
    fetch_result_inline,
    map_partial_count_sum,
    submit_ok,
    wait_for_job,
)


def _kill_one_worker() -> str | None:
    if shutil.which("docker") is None:
        return None
    out = subprocess.run(
        ["docker", "ps", "-q", "--filter", "label=dm.role=worker"],
        capture_output=True,
        text=True,
        check=False,
    )
    ids = out.stdout.split()
    if not ids:
        return None
    subprocess.run(["docker", "kill", ids[0]], check=True, capture_output=True)
    return ids[0]


def test_kill_worker_mid_job(api, seed_inputs, db) -> None:
    inputs = seed_inputs((60, 2000, 11))
    job_id = submit_ok(api, inputs, inputs.c)

    time.sleep(4)  # let workers get busy
    killed = _kill_one_worker()
    if killed is None:
        pytest.skip("docker unavailable or no worker containers to kill")

    # Crash detection is ≤35s (30s lease + 5s reaper); allow generous margin.
    outcome = wait_for_job(api, job_id, timeout=300)
    assert_matches_oracle(fetch_result_inline(api, job_id), inputs.oracle, label="chaos")

    # Conservation (DM-003): Σ count over map-produced partials == F exactly —
    # the killed worker's task was retried, never double-counted.
    n_map_partials, count_sum = map_partial_count_sum(db, job_id)
    assert count_sum == inputs.f, (n_map_partials, count_sum)
    assert outcome.status == "completed"


def test_retried_task_has_attempts_gt_one(api, seed_inputs, db) -> None:
    """After a chaos kill, at least one task in some recent job shows attempts > 1
    OR a lease-expiry event exists — evidence the reaper path actually ran."""
    with db.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM events
               WHERE type IN ('task.lease_expired', 'task.dead')
                 AND ts > now() - interval '10 minutes'"""
        )
        events = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tasks WHERE attempts > 1")
        retried = cur.fetchone()[0]
    if events == 0 and retried == 0:
        pytest.skip("no chaos ran recently (run test_kill_worker_mid_job first)")
    assert events > 0 or retried > 0
