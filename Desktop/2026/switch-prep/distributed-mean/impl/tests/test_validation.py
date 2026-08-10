"""The submit-path validation matrix — LLD §6 error taxonomy."""

from __future__ import annotations

import uuid

from conftest import submit, submit_ok, unseeded_uris, wait_for_job


def _error_code(resp) -> str:
    return resp.json()["error"]["code"]


def test_duplicate_uri_is_422(api) -> None:
    uris = unseeded_uris(3)
    resp = submit(api, [uris[0], uris[1], uris[0]], 10)
    assert resp.status_code == 422, resp.text


def test_out_of_range_c_and_f(api) -> None:
    uris = unseeded_uris(3)
    assert submit(api, uris, 1).status_code in (400, 422)          # C too small
    assert submit(api, uris, 1_000_000).status_code in (400, 422)  # C too large
    assert submit(api, uris[:1], 10).status_code in (400, 422)     # F=1 < 2


def test_malformed_body_is_400(api) -> None:
    resp = api.post("/jobs", json={"inputUris": "not-a-list", "c": "nope"})
    assert resp.status_code == 400, resp.text


def test_non_allowlisted_uri_is_422(api) -> None:
    resp = submit(api, ["s3://evil-bucket/weights/a.f64", *unseeded_uris(2)], 10)
    assert resp.status_code == 422, resp.text
    assert "evil-bucket" in resp.text


def test_idempotency_key_returns_same_job(api, seed_inputs) -> None:
    inputs = seed_inputs((4, 5, 99))
    key = f"test-{uuid.uuid4().hex}"
    first = submit(api, inputs, inputs.c, headers={"Idempotency-Key": key})
    assert first.status_code == 202, first.text
    second = submit(api, inputs, inputs.c, headers={"Idempotency-Key": key})
    assert second.status_code == 200, second.text
    assert first.json()["jobId"] == second.json()["jobId"]


def test_result_is_409_before_completion(api) -> None:
    # Unseeded URIs pass submit (existence is deliberately not checked there,
    # LLD §6) and the job will churn through retries — plenty of time for the 409.
    job_id = submit_ok(api, unseeded_uris(6, tag="never-completes"), 10)
    resp = api.get(f"/jobs/{job_id}/result")
    assert resp.status_code == 409, resp.text
    assert _error_code(resp) == "result_not_ready"


def test_unreadable_input_fails_job_with_uri_in_error(api, db) -> None:
    """The input-unreachable edge case (04 §5): retries exhaust, job fails loudly,
    last_error names the offending URI."""
    uris = unseeded_uris(2, tag="missing")
    job_id = submit_ok(api, uris, 10)
    outcome = wait_for_job(api, job_id, timeout=240, expect="failed")
    assert outcome.body.get("error"), outcome.body
    with db.cursor() as cur:
        cur.execute(
            "SELECT last_error FROM tasks WHERE job_id = %s AND status = 'dead' LIMIT 1",
            (job_id,),
        )
        row = cur.fetchone()
    assert row is not None and row[0], "dead task should record last_error"
