"""The brief's own worked example — the system's primary acceptance test.

F=2, C=3, inputs [1,2,3] and [4,5,6] → the result file is exactly
[2.5, 3.5, 4.5] (00-problem-statement §Example)."""

from __future__ import annotations

import numpy as np

from conftest import fetch_result_inline, submit_ok, wait_for_job


def test_prompt_example_inline(api, seed_inputs, submit_and_wait) -> None:
    inputs = seed_inputs([[1, 2, 3], [4, 5, 6]], formats="csv")
    outcome = submit_and_wait(inputs, inputs.c)
    got = fetch_result_inline(api, outcome.job_id)
    # Exact, not approximate: these values are representable in float64.
    assert got.tolist() == [2.5, 3.5, 4.5], got


def test_prompt_example_presigned_redirect(api, raw_http, seed_inputs) -> None:
    inputs = seed_inputs([[1, 2, 3], [4, 5, 6]])
    job_id = submit_ok(api, inputs, inputs.c)
    wait_for_job(api, job_id)

    resp = api.get(f"/jobs/{job_id}/result")  # api client does not follow redirects
    assert resp.status_code == 302, resp.text
    url = resp.headers["location"]
    body = raw_http.get(url)  # pre-signed: no auth headers required
    assert body.status_code == 200, f"presigned GET → {body.status_code}"
    values = np.array([float(x) for x in body.text.split()])
    assert values.tolist() == [2.5, 3.5, 4.5]
