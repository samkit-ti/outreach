"""Correctness against the numpy oracle (01-requirements §6)."""

from __future__ import annotations

import pytest

from conftest import assert_matches_oracle, fetch_result_inline


def test_golden_f7_drain_fanin(api, seed_inputs, submit_and_wait) -> None:
    """F=7 (chunks 5+2) exercises F%5≠0 and drain-mode fan-in 2 (DM-002)."""
    inputs = seed_inputs((7, 10, 42))
    outcome = submit_and_wait(inputs, inputs.c)
    assert_matches_oracle(fetch_result_inline(api, outcome.job_id), inputs.oracle, label="F=7")


def test_mixed_input_formats(api, seed_inputs, submit_and_wait) -> None:
    """Alternating .csv and .f64 inputs in one job (DM-005 dual format)."""
    inputs = seed_inputs((9, 25, 7), formats="mixed")
    outcome = submit_and_wait(inputs, inputs.c)
    assert_matches_oracle(fetch_result_inline(api, outcome.job_id), inputs.oracle, label="mixed")


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_property_random_small_jobs(api, seed_inputs, submit_and_wait, seed: int) -> None:
    """Random (F ≤ 40, C ≤ 50) jobs vs the oracle — the tree shape varies per run."""
    import numpy as np

    rng = np.random.default_rng(seed)
    f = int(rng.integers(2, 41))
    c = int(rng.integers(2, 51))
    inputs = seed_inputs((f, c, seed * 1000))
    outcome = submit_and_wait(inputs, inputs.c)
    assert_matches_oracle(
        fetch_result_inline(api, outcome.job_id), inputs.oracle, label=f"F={f},C={c}"
    )
