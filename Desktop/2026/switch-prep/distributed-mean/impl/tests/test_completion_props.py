"""Completion and observability properties (DM-003, DM-009)."""

from __future__ import annotations

from conftest import q1, read_sse, submit_ok, wait_for_job


def test_completion_properties(api, db, seed_inputs) -> None:
    inputs = seed_inputs((12, 50, 33))
    job_id = submit_ok(api, inputs, inputs.c)
    outcome = wait_for_job(api, job_id)

    # Exactly one finalize task, and it is done (the running→finalizing CAS).
    assert q1(db, "SELECT count(*) FROM tasks WHERE job_id=%s AND type='finalize'", (job_id,)) == 1
    assert (
        q1(db, "SELECT count(*) FROM tasks WHERE job_id=%s AND type='finalize' AND status='done'", (job_id,))
        == 1
    )
    # A job.completed event exists.
    assert q1(db, "SELECT count(*) FROM events WHERE job_id=%s AND type='job.completed'", (job_id,)) == 1
    # The root partial covers all F files and was never consumed (finalize reads, not consumes).
    assert q1(
        db,
        "SELECT count(*) FROM partials WHERE job_id=%s AND consumed_by IS NULL AND count=%s",
        (job_id, inputs.f),
    ) == 1


def test_progress_monotone_and_100_only_at_completion(api, seed_inputs, submit_and_wait) -> None:
    """DM-009: coverage-based progress never decreases, and 1.0 appears only on
    the terminal 'completed' sample."""
    inputs = seed_inputs((40, 500, 44))
    outcome = submit_and_wait(inputs, inputs.c)
    progressed = [(s, p) for _, s, p in outcome.samples if p is not None]
    values = [p for _, p in progressed]
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:])), values
    for status, p in progressed:
        if p >= 1.0:
            assert status == "completed", (status, p)


def test_sse_stream_shape(api_url, api, seed_inputs) -> None:
    """GET /events emits parseable frames including 1 Hz snapshots, and event ids
    are strictly increasing (the 1-second-lag tail contract)."""
    inputs = seed_inputs((10, 50, 55))
    submit_ok(api, inputs, inputs.c)

    frames = read_sse(f"{api_url}/events", seconds=6)
    assert frames, "no SSE frames within 6s"
    snapshots = [f for f in frames if f.event == "snapshot"]
    assert snapshots, "no snapshot frames — expected ~1 Hz"
    stats = snapshots[-1].json()
    assert "workers" in stats and "jobs" in stats and "tasks" in stats

    ids = [f.id for f in frames if f.id is not None]
    assert ids == sorted(ids), f"event ids out of order: {ids}"
    assert len(set(ids)) == len(ids), "duplicate event ids on the stream"
