"""
Black-box test harness for the Distributed Mean system.

Contract under test: docs/03-lld.md (§1 DDL, §3 claim query, §4 T1-T4, §6 API, §7 object
layout, §8 config, §10 test plan), docs/01-requirements-and-assumptions.md §6, and ITDs
DM-003 (completion proof), DM-006 (fencing / at-least-once), DM-007 (fairness),
DM-009 (events + SSE).

**Nothing here imports from impl/api or impl/worker.** Every assertion is made through the
public HTTP surface, or directly against Postgres / the S3-API object store, exactly as an
external operator would. That is the point: the suite is a check on the *contract*, not on
the implementation's own beliefs about itself.

Collection is always safe: reachability is probed inside fixtures, never at import time, so
`pytest --collect-only` succeeds on a machine with no stack running and every live test
skips with a reason.
"""

from __future__ import annotations

import io
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence

import httpx
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Environment (LLD §8; docker-compose topology LLD §9)
# ---------------------------------------------------------------------------

API_URL = os.environ.get("API_URL", "http://localhost:8080").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://dm:dm@localhost:5433/dm")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000").rstrip("/")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "dmadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "dmsecret")
S3_BUCKET = os.environ.get("S3_BUCKET", "distributed-mean")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

#: Every seeded fixture URI lives under this scheme+bucket, which is what the API's default
#: ``INPUT_URI_ALLOWLIST`` (``s3://distributed-mean/``) permits. Fixtures go under
#: ``fixtures/`` — never under ``jobs/{jobId}/``, which is the *write* namespace (LLD §7),
#: so the read/write asymmetry is exercised rather than short-circuited.
ALLOWLIST_ROOT = f"s3://{S3_BUCKET}/"
FIXTURE_PREFIX = os.environ.get("DM_FIXTURE_PREFIX", "fixtures").strip("/")

#: Default ceiling for submit→completed. Generous: a chaos or fairness run pays a 35 s
#: worst-case crash-detection latency (LLD §3) on top of real work.
JOB_TIMEOUT = float(os.environ.get("JOB_TIMEOUT", "300"))
#: How hard we probe for liveness before deciding the stack is absent.
PROBE_TIMEOUT = float(os.environ.get("DM_PROBE_TIMEOUT", "3"))
#: Polling cadence for GET /jobs/:id.
POLL_INTERVAL = float(os.environ.get("DM_POLL_INTERVAL", "0.35"))

#: Numerical tolerance from 01-requirements §6 ("within 1e-9 relative error"). The absolute
#: term only exists so that a true zero in the oracle does not make the relative test vacuous.
RTOL = 1e-9
ATOL = 1e-12


# ---------------------------------------------------------------------------
# Reachability probes — cached, and only ever called from inside a fixture
# ---------------------------------------------------------------------------

_probe_cache: dict[str, str | None] = {}


def _probe(key: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` once per session; skip the calling test with its error if it failed.

    Caching matters for more than speed: without it, a suite run against an absent stack
    pays a TCP timeout per test.
    """
    if key not in _probe_cache:
        try:
            fn()
            _probe_cache[key] = None
        except Exception as err:  # noqa: BLE001 - any failure means "not reachable"
            _probe_cache[key] = f"{type(err).__name__}: {err}"
    reason = _probe_cache[key]
    if reason is not None:
        pytest.skip(f"live stack not reachable ({key}): {reason}")


def _probe_api_fn() -> None:
    with httpx.Client(timeout=PROBE_TIMEOUT) as client:
        resp = client.get(f"{API_URL}/system/stats")
    if resp.status_code >= 500:
        raise RuntimeError(f"GET {API_URL}/system/stats returned {resp.status_code}")


def _probe_db_fn() -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL, connect_timeout=int(max(1, PROBE_TIMEOUT))) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


def _probe_s3_fn() -> None:
    client = _make_s3_client()
    client.head_bucket(Bucket=S3_BUCKET)


def _make_s3_client() -> Any:
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # MinIO
            connect_timeout=int(max(1, PROBE_TIMEOUT)),
            read_timeout=30,
            retries={"max_attempts": 3},
        ),
    )


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_url() -> str:
    """The API base URL, having verified something is answering on it."""
    _probe("api", _probe_api_fn)
    return API_URL


@pytest.fixture
def api(api_url: str) -> Iterator[httpx.Client]:
    """HTTP client for the API.

    ``follow_redirects=False`` is deliberate: ``GET /jobs/:id/result`` answers ``302`` to a
    pre-signed URL (LLD §6), and a client that silently followed it could not tell the
    redirect mode from the ``?inline=1`` mode.
    """
    with httpx.Client(base_url=api_url, timeout=30.0, follow_redirects=False) as client:
        yield client


@pytest.fixture
def raw_http() -> Iterator[httpx.Client]:
    """Client with no base URL — for fetching pre-signed URLs the API hands back."""
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        yield client


@pytest.fixture
def db() -> Iterator[Any]:
    """Autocommit Postgres connection for read-only assertions.

    Autocommit keeps assertion reads from pinning a snapshot while a job progresses, and
    keeps a failed test from leaving an idle-in-transaction connection behind. Tests that
    need explicit transaction control (test_pairing_pinned) open their own connections.
    """
    _probe("db", _probe_db_fn)
    import psycopg

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_connect() -> Iterator[Callable[..., Any]]:
    """Factory for extra connections, all closed at teardown.

    Used by the pinned-interleaving test, which needs several concurrent sessions with
    independent transaction state.
    """
    _probe("db", _probe_db_fn)
    import psycopg

    opened: list[Any] = []

    def connect(*, autocommit: bool = False) -> Any:
        conn = psycopg.connect(DATABASE_URL, autocommit=autocommit)
        opened.append(conn)
        return conn

    try:
        yield connect
    finally:
        for conn in opened:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass


@pytest.fixture
def s3() -> Any:
    """boto3 S3 client pointed at the object store (MinIO locally)."""
    _probe("s3", _probe_s3_fn)
    return _make_s3_client()


# ---------------------------------------------------------------------------
# Fixture seeding (the harness role of `make seed`, per 01-requirements A-2)
# ---------------------------------------------------------------------------


@dataclass
class SeededInputs:
    """A seeded input set: the URIs to submit, plus the ground truth to check against.

    Behaves like the ``inputUris`` list it carries (iterable, indexable, sized) so it can be
    passed straight into a submit call, while still exposing ``.values`` and ``.oracle`` for
    the correctness assertion.
    """

    uris: list[str]
    values: np.ndarray  # shape (F, C), float64
    formats: list[str] = field(default_factory=list)

    @property
    def f(self) -> int:
        return int(self.values.shape[0])

    @property
    def c(self) -> int:
        return int(self.values.shape[1])

    @property
    def oracle(self) -> np.ndarray:
        """The single-node numpy reference mean — 01-requirements §6 correctness proof."""
        return self.values.mean(axis=0)

    def __iter__(self) -> Iterator[str]:
        return iter(self.uris)

    def __len__(self) -> int:
        return len(self.uris)

    def __getitem__(self, i: int) -> str:
        return self.uris[i]


def _encode_f64(vec: np.ndarray) -> bytes:
    """Raw little-endian float64 × C (LLD §7)."""
    return np.ascontiguousarray(vec, dtype="<f8").tobytes()


def _encode_csv(vec: np.ndarray) -> bytes:
    """One value per line, exactly C lines (LLD §7).

    No trailing newline: the reader validates ``line count == C``, and a trailing newline
    makes that count ambiguous. ``repr`` round-trips a float64 exactly, so the CSV and
    ``.f64`` encodings of the same vector are the same numbers — which is what the
    mixed-format test rests on.
    """
    return "\n".join(repr(float(x)) for x in vec).encode("ascii")


@pytest.fixture
def seed_inputs(s3: Any) -> Iterator[Callable[..., SeededInputs]]:
    """Write fixture input files to the object store and return their URIs.

    ``spec`` is either an explicit matrix of values (``list[list[float]]`` / ndarray, shape
    F×C) or a ``(f, c, seed)`` tuple for a reproducible random matrix.

    ``formats`` is ``"f64"`` (default), ``"csv"``, ``"mixed"`` (alternating, for the
    mixed-format golden test), or an explicit per-file list.

    Files land under ``fixtures/{uuid}/`` — inside the allow-listed bucket but outside the
    ``jobs/{jobId}/`` write namespace — and are deleted at teardown.
    """
    created: list[str] = []

    def _seed(
        spec: Sequence[Sequence[float]] | np.ndarray | tuple[int, int, int],
        *,
        formats: str | Sequence[str] = "f64",
    ) -> SeededInputs:
        if isinstance(spec, tuple) and len(spec) == 3 and all(isinstance(x, int) for x in spec):
            f, c, seed = spec
            rng = np.random.default_rng(seed)
            values = rng.standard_normal((f, c)).astype(np.float64)
        else:
            values = np.asarray(spec, dtype=np.float64)
            if values.ndim != 2:
                raise ValueError(f"expected an F×C matrix, got shape {values.shape}")
            f = int(values.shape[0])

        if isinstance(formats, str):
            if formats == "mixed":
                per_file = ["csv" if i % 2 else "f64" for i in range(f)]
            else:
                per_file = [formats] * f
        else:
            per_file = list(formats)
            if len(per_file) != f:
                raise ValueError(f"formats has {len(per_file)} entries for F={f}")

        batch = f"{FIXTURE_PREFIX}/{uuid.uuid4()}"
        uris: list[str] = []
        jobs: list[tuple[str, bytes]] = []
        for i, fmt in enumerate(per_file):
            if fmt == "f64":
                body = _encode_f64(values[i])
            elif fmt == "csv":
                body = _encode_csv(values[i])
            else:
                raise ValueError(f"unknown fixture format {fmt!r}")
            key = f"{batch}/{i:06d}.{fmt}"
            jobs.append((key, body))
            uris.append(f"s3://{S3_BUCKET}/{key}")

        # Parallel PUTs: the fairness test seeds hundreds of files and a serial loop would
        # dominate its wall clock.
        def put(item: tuple[str, bytes]) -> None:
            key, body = item
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=io.BytesIO(body))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(put, jobs))
        created.extend(key for key, _ in jobs)

        return SeededInputs(uris=uris, values=values, formats=per_file)

    try:
        yield _seed
    finally:
        for i in range(0, len(created), 1000):
            chunk = created[i : i + 1000]
            try:
                s3.delete_objects(
                    Bucket=S3_BUCKET,
                    Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
                )
            except Exception:  # noqa: BLE001 - fixture cleanup is best-effort
                pass


def unseeded_uris(n: int, tag: str = "unseeded") -> list[str]:
    """N distinct, allow-listed, *non-existent* input URIs.

    Legitimate for submit-path tests only, and only because LLD §6 states outright that
    object existence and length are deliberately **not** validated at submit (that would be
    F HEAD requests on the submit path). These URIs pass every submit check and would fail
    at read.
    """
    batch = uuid.uuid4()
    return [f"s3://{S3_BUCKET}/{FIXTURE_PREFIX}/{tag}/{batch}/{i:06d}.f64" for i in range(n)]


# ---------------------------------------------------------------------------
# Job submission / polling helpers
# ---------------------------------------------------------------------------

#: Terminal job states (LLD §1 ``job_status``).
TERMINAL = {"completed", "failed"}


class JobFailed(AssertionError):
    """A job reached ``failed`` when the test expected it to complete."""


class JobTimeout(AssertionError):
    """A job did not reach a terminal state inside the test's budget."""


def submit(api: httpx.Client, input_uris: Sequence[str], c: int, **kw: Any) -> httpx.Response:
    """Raw ``POST /jobs`` — returns the response untouched so status codes can be asserted."""
    headers = kw.pop("headers", None)
    return api.post("/jobs", json={"inputUris": list(input_uris), "c": c}, headers=headers, **kw)


def submit_ok(api: httpx.Client, input_uris: Sequence[str], c: int, **kw: Any) -> str:
    """``POST /jobs`` expecting the documented ``202 {jobId}`` and returning the job id."""
    resp = submit(api, input_uris, c, **kw)
    assert resp.status_code == 202, f"POST /jobs → {resp.status_code}: {resp.text[:400]}"
    body = resp.json()
    job_id = body.get("jobId")
    assert isinstance(job_id, str) and job_id, f"no jobId in {body!r}"
    return job_id


def poll_job(api: httpx.Client, job_id: str) -> dict[str, Any]:
    """``GET /jobs/:id`` → ``{status, progress, counts:{...}, error?}`` (LLD §6)."""
    resp = api.get(f"/jobs/{job_id}")
    assert resp.status_code == 200, f"GET /jobs/{job_id} → {resp.status_code}: {resp.text[:400]}"
    return resp.json()


@dataclass
class JobOutcome:
    """Terminal state of a job plus every ``(elapsed, status, progress)`` sample seen.

    The sample trail is what makes the DM-009 progress claims testable after the fact:
    monotonicity, and "only ``finalize`` writes 100%".
    """

    job_id: str
    status: str
    body: dict[str, Any]
    samples: list[tuple[float, str, float | None]]
    elapsed: float


def wait_for_job(
    api: httpx.Client,
    job_id: str,
    *,
    timeout: float = JOB_TIMEOUT,
    expect: str = "completed",
) -> JobOutcome:
    """Poll ``GET /jobs/:id`` until terminal, recording every sample."""
    started = time.monotonic()
    deadline = started + timeout
    samples: list[tuple[float, str, float | None]] = []
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = poll_job(api, job_id)
        status = str(body.get("status", ""))
        progress = body.get("progress")
        samples.append(
            (
                time.monotonic() - started,
                status,
                float(progress) if isinstance(progress, (int, float)) else None,
            )
        )
        if status in TERMINAL:
            outcome = JobOutcome(job_id, status, body, samples, time.monotonic() - started)
            if expect and status != expect:
                raise JobFailed(
                    f"job {job_id} reached {status!r}, expected {expect!r}; "
                    f"error={body.get('error')!r}"
                )
            return outcome
        time.sleep(POLL_INTERVAL)
    raise JobTimeout(
        f"job {job_id} still {body.get('status')!r} after {timeout}s "
        f"(progress={body.get('progress')!r}, counts={body.get('counts')!r})"
    )


@pytest.fixture
def submit_and_wait(api: httpx.Client) -> Callable[..., JobOutcome]:
    """Submit a job and block until it reaches a terminal state."""

    def _run(
        input_uris: Sequence[str],
        c: int,
        *,
        timeout: float = JOB_TIMEOUT,
        expect: str = "completed",
        headers: dict[str, str] | None = None,
    ) -> JobOutcome:
        job_id = submit_ok(api, input_uris, c, headers=headers)
        return wait_for_job(api, job_id, timeout=timeout, expect=expect)

    return _run


# ---------------------------------------------------------------------------
# Result retrieval (LLD §6: 302 pre-signed | ?inline=1 stream | 409 until completed)
# ---------------------------------------------------------------------------


def parse_result_csv(text: str) -> np.ndarray:
    """Parse the result object: one float per line, C lines (LLD §7)."""
    lines = [ln for ln in text.replace("\r\n", "\n").strip().split("\n") if ln.strip()]
    return np.array([float(ln) for ln in lines], dtype=np.float64)


def fetch_result_inline(api: httpx.Client, job_id: str) -> np.ndarray:
    """``GET /jobs/:id/result?inline=1`` → the streamed result vector."""
    resp = api.get(f"/jobs/{job_id}/result", params={"inline": 1})
    assert resp.status_code == 200, (
        f"GET /jobs/{job_id}/result?inline=1 → {resp.status_code}: {resp.text[:400]}"
    )
    return parse_result_csv(resp.text)


@pytest.fixture
def fetch_result(api: httpx.Client) -> Callable[[str], np.ndarray]:
    """Download a completed job's result vector via the inline mode."""

    def _fetch(job_id: str) -> np.ndarray:
        return fetch_result_inline(api, job_id)

    return _fetch


def assert_matches_oracle(actual: np.ndarray, oracle: np.ndarray, *, label: str = "") -> None:
    """Assert the system's result equals the numpy single-node reference.

    Tolerance is 1e-9 relative (01-requirements §6). Exact equality is not asserted in
    general because the system sums over a reduction *tree* while numpy sums pairwise — a
    different, equally valid association order, so the two agree to rounding rather than
    bit-for-bit (DM-010).
    """
    prefix = f"{label}: " if label else ""
    assert actual.shape == oracle.shape, (
        f"{prefix}result has {actual.shape} values, oracle has {oracle.shape}"
    )
    assert np.all(np.isfinite(actual)), f"{prefix}result contains non-finite values"
    if not np.allclose(actual, oracle, rtol=RTOL, atol=ATOL):
        err = np.abs(actual - oracle) / np.maximum(np.abs(oracle), 1e-300)
        worst = int(np.argmax(err))
        raise AssertionError(
            f"{prefix}result != numpy oracle beyond rtol={RTOL}: worst index {worst} "
            f"actual={actual[worst]!r} oracle={oracle[worst]!r} rel_err={err[worst]:.3e}"
        )


# ---------------------------------------------------------------------------
# Direct DB assertions (LLD §1 schema; DM-003 invariants)
# ---------------------------------------------------------------------------


def q1(db: Any, sql: str, params: Sequence[Any] = ()) -> Any:
    """Scalar query helper."""
    with db.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return None if row is None else row[0]


def qall(db: Any, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    """All-rows query helper."""
    with db.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def job_row(db: Any, job_id: str) -> tuple[Any, ...] | None:
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, f, c, status, result_uri, error, created_at, completed_at "
            "FROM jobs WHERE id = %s",
            (job_id,),
        )
        return cur.fetchone()


def map_partial_count_sum(db: Any, job_id: str) -> tuple[int, int]:
    """``(rows, Σ count)`` over partials produced by this job's ``map`` tasks.

    DM-003 conservation: every one of the F inputs is covered by exactly one map task, and
    a map partial's ``count`` is the number of inputs it covers, so this sum is exactly F —
    unless the completion GC has already dropped the job's ``partials`` rows (LLD §7),
    which is why the row count comes back too.
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*), COALESCE(SUM(p.count), 0) "
            "FROM partials p JOIN tasks t ON t.id = p.produced_by "
            "WHERE p.job_id = %s AND t.type = 'map'",
            (job_id,),
        )
        rows, total = cur.fetchone()
    return int(rows), int(total)


def wait_until(
    predicate: Callable[[], bool], *, timeout: float, interval: float = 0.25, what: str = "condition"
) -> None:
    """Block until ``predicate`` holds, or fail with what we were waiting for."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


# ---------------------------------------------------------------------------
# SSE (DM-009 / LLD §6 GET /events)
# ---------------------------------------------------------------------------


@dataclass
class SseFrame:
    """One parsed ``text/event-stream`` frame."""

    id: int | None
    event: str | None
    data: str

    def json(self) -> Any:
        import json

        return json.loads(self.data)


def read_sse(url: str, *, seconds: float, max_frames: int = 500) -> list[SseFrame]:
    """Tail ``GET /events`` for a bounded window and return the parsed frames.

    The frame wire format is ``id: N\\nevent: type\\ndata: {...}\\n\\n`` (DM-009). Lines
    beginning with ``:`` are keepalive comments and carry no frame.
    """
    frames: list[SseFrame] = []
    deadline = time.monotonic() + seconds
    cur_id: int | None = None
    cur_event: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_id, cur_event, data_lines
        if data_lines:
            frames.append(SseFrame(cur_id, cur_event, "\n".join(data_lines)))
        cur_id, cur_event, data_lines = None, None, []

    with httpx.Client(timeout=httpx.Timeout(seconds + 15.0, read=seconds + 15.0)) as client:
        with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp:
            assert resp.status_code == 200, f"GET /events → {resp.status_code}"
            ctype = resp.headers.get("content-type", "")
            assert "text/event-stream" in ctype, f"GET /events content-type is {ctype!r}"
            for line in resp.iter_lines():
                if time.monotonic() > deadline or len(frames) >= max_frames:
                    break
                line = line.rstrip("\r")
                if line == "":
                    flush()
                    continue
                if line.startswith(":"):
                    continue  # keepalive comment
                field, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if field == "id":
                    try:
                        cur_id = int(value)
                    except ValueError:
                        cur_id = None
                elif field == "event":
                    cur_event = value
                elif field == "data":
                    data_lines.append(value)
    flush()
    return frames
