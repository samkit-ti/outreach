"""Fairness (DM-007): a small job entering behind a big one finishes in ~its own
work time, not after the convoy."""

from __future__ import annotations

import time

from conftest import submit_ok, wait_for_job


def test_small_job_not_starved_by_big_job(api, seed_inputs) -> None:
    big = seed_inputs((300, 5000, 21))
    small = seed_inputs((10, 5000, 22))

    t0 = time.monotonic()
    big_id = submit_ok(api, big, big.c)
    time.sleep(3)  # the big job now owns the queue
    small_submitted = time.monotonic() - t0
    small_id = submit_ok(api, small, small.c)

    small_outcome = wait_for_job(api, small_id, timeout=300)
    small_done = time.monotonic() - t0
    big_outcome = wait_for_job(api, big_id, timeout=600)
    big_done = time.monotonic() - t0

    small_makespan = small_done - small_submitted
    big_makespan = big_done
    # Least-in-flight ordering: the small job's makespan is a small fraction of the
    # big job's, and it finishes strictly earlier (DM-007's quantified claim).
    assert small_done < big_done, (small_done, big_done)
    assert small_makespan < 0.5 * big_makespan, (
        f"small={small_makespan:.1f}s big={big_makespan:.1f}s — fairness ordering "
        "should keep the small job's wait near its own work time"
    )
    assert small_outcome.status == big_outcome.status == "completed"
