"""Unit tests — pure logic, no DB, no S3 (the FakeStore stands in)."""

from __future__ import annotations

import numpy as np
import pytest

from worker.blobstore import (
    is_read_allowed,
    is_write_allowed,
    parse_s3_uri,
    partial_key,
    result_key,
)
from worker.errors import PermanentInputError
from worker.executors import Executor, encode_partial, parse_input
from worker.types import ClaimedTask, parse_payload


class FakeStore:
    """In-memory BlobStore honouring the same guard semantics."""

    def __init__(self, bucket: str = "distributed-mean") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}

    def get(self, uri: str) -> bytes:
        return self.objects[uri]

    def put(self, uri: str, body: bytes, *, job_id: str) -> None:
        assert is_write_allowed(uri, job_id=job_id, own_bucket=self.bucket), uri
        self.objects[uri] = body


# ---------- key/guard helpers ----------

def test_partial_and_result_keys() -> None:
    assert partial_key("j1", "t1") == "jobs/j1/partials/t1.f64"
    assert result_key("j1") == "jobs/j1/result.csv"


def test_uri_parse_rejects_traversal_and_query() -> None:
    with pytest.raises(PermanentInputError):
        parse_s3_uri("s3://b/jobs/../other/x")
    with pytest.raises(PermanentInputError):
        parse_s3_uri("s3://b/k?versionId=1")
    with pytest.raises(PermanentInputError):
        parse_s3_uri("https://b/k")


def test_read_allowlist_is_bucket_exact_not_string_prefix() -> None:
    allow = ("s3://distributed-mean/fixtures/",)
    assert is_read_allowed(
        "s3://distributed-mean/fixtures/a.csv", allowlist=allow, own_bucket="dm-x"
    )
    # the classic startswith bug: an evil bucket sharing the string prefix
    assert not is_read_allowed(
        "s3://distributed-mean-evil/fixtures/a.csv", allowlist=allow, own_bucket="dm-x"
    )
    # our own bucket is always readable (partials)
    assert is_read_allowed("s3://dm-x/jobs/j/partials/t.f64", allowlist=allow, own_bucket="dm-x")


def test_write_confined_to_job_prefix() -> None:
    assert is_write_allowed("s3://b/jobs/j1/partials/t.f64", job_id="j1", own_bucket="b")
    assert not is_write_allowed("s3://b/jobs/j2/partials/t.f64", job_id="j1", own_bucket="b")
    assert not is_write_allowed("s3://other/jobs/j1/x", job_id="j1", own_bucket="b")


# ---------- input parsing ----------

def test_parse_input_csv_and_f64_roundtrip() -> None:
    vec = np.array([1.5, -2.25, 3.125])
    body_csv = b"1.5\n-2.25\n3.125\n"
    np.testing.assert_array_equal(parse_input("s3://b/x.csv", body_csv, c=3), vec)
    np.testing.assert_array_equal(
        parse_input("s3://b/x.f64", encode_partial(vec), c=3), vec
    )


def test_parse_input_length_mismatch_names_uri() -> None:
    with pytest.raises(PermanentInputError, match="s3://b/x.csv"):
        parse_input("s3://b/x.csv", b"1\n2\n", c=3)
    with pytest.raises(PermanentInputError, match="declared C=3"):
        parse_input("s3://b/x.f64", b"\x00" * 16, c=3)


def test_parse_input_unknown_extension() -> None:
    with pytest.raises(PermanentInputError, match="unknown input extension"):
        parse_input("s3://b/x.parquet", b"", c=3)


# ---------- payload parsing ----------

def test_payload_rejects_duplicate_uris_and_kind_mismatch() -> None:
    with pytest.raises(PermanentInputError, match="repeats an input URI"):
        parse_payload(
            "map",
            {"kind": "map", "jobId": "j", "inputUris": ["s3://b/a.csv", "s3://b/a.csv"], "c": 3},
            k_fanin=5,
        )
    with pytest.raises(PermanentInputError, match="disagrees"):
        parse_payload("reduce", {"kind": "map", "jobId": "j", "inputUris": ["u"], "c": 1}, k_fanin=5)


# ---------- the brief's worked example, through the real executors ----------

def _claimed(task_id: str, type_: str, payload: dict) -> ClaimedTask:
    return ClaimedTask(
        id=task_id,
        type=type_,  # type: ignore[arg-type]
        payload=parse_payload(type_, payload, k_fanin=5),
        lease_token="tok",
        job_id=payload["jobId"],
    )


def test_prompt_example_map_then_finalize() -> None:
    """F=2, C=3, files [1,2,3] and [4,5,6] → [2.5, 3.5, 4.5] exactly."""
    store = FakeStore()
    store.objects["s3://distributed-mean/fixtures/a.csv"] = b"1\n2\n3\n"
    store.objects["s3://distributed-mean/fixtures/b.csv"] = b"4\n5\n6\n"
    ex = Executor(store, speed_factor=1.0)

    map_task = _claimed(
        "t-map",
        "map",
        {
            "kind": "map",
            "jobId": "j1",
            "inputUris": [
                "s3://distributed-mean/fixtures/a.csv",
                "s3://distributed-mean/fixtures/b.csv",
            ],
            "c": 3,
        },
    )
    map_result = ex.execute(map_task)
    assert map_result.count == 2

    fin_task = _claimed(
        "t-fin",
        "finalize",
        {"kind": "finalize", "jobId": "j1", "partialUri": map_result.output_uri, "f": 2, "c": 3},
    )
    fin_result = ex.execute(fin_task)
    lines = store.objects[fin_result.output_uri].decode().split()
    assert [float(x) for x in lines] == [2.5, 3.5, 4.5]


def test_map_reduce_finalize_matches_numpy_oracle() -> None:
    """F=7 (chunks 5+2, drain fan-in 2) against numpy.mean(axis=0)."""
    rng = np.random.default_rng(42)
    c, f = 11, 7
    data = rng.random((f, c))
    store = FakeStore()
    uris = []
    for i in range(f):
        uri = f"s3://distributed-mean/fixtures/{i}.f64"
        store.objects[uri] = encode_partial(data[i])
        uris.append(uri)
    ex = Executor(store, speed_factor=1.0)

    m1 = ex.execute(_claimed("m1", "map", {"kind": "map", "jobId": "j", "inputUris": uris[:5], "c": c}))
    m2 = ex.execute(_claimed("m2", "map", {"kind": "map", "jobId": "j", "inputUris": uris[5:], "c": c}))
    r1 = ex.execute(
        _claimed(
            "r1",
            "reduce",
            {
                "kind": "reduce",
                "jobId": "j",
                "partialIds": ["p1", "p2"],
                "partialUris": [m1.output_uri, m2.output_uri],
                "c": c,
            },
        )
    )
    fin = ex.execute(
        _claimed("fz", "finalize", {"kind": "finalize", "jobId": "j", "partialUri": r1.output_uri, "f": f, "c": c})
    )
    got = np.array([float(x) for x in store.objects[fin.output_uri].decode().split()])
    np.testing.assert_allclose(got, data.mean(axis=0), rtol=1e-9)
