"""The three executors — pure compute + blob I/O, NO database writes (LLD §5).

Every output key is a deterministic function of the task's inputs, so a retry
overwrites itself byte-identically (DM-006). ``SPEED_FACTOR`` implements the
straggler demo by sleeping ``elapsed × (factor − 1)`` after the real work.
"""

from __future__ import annotations

import time

import numpy as np

from .blobstore import BlobStore, partial_key, result_key
from .errors import NumericsError, PermanentInputError
from .types import (
    ClaimedTask,
    FinalizePayload,
    MapPayload,
    ReducePayload,
    TaskResult,
)

_F64 = np.dtype("<f8")  # little-endian float64 — LLD §7


def parse_input(uri: str, body: bytes, *, c: int) -> np.ndarray:
    """Decode one input object (.csv one-float-per-line, or raw .f64) and
    validate its length against the declared C. A mismatch names the URI, the
    declared C, and the length found (LLD §4 T4's ``last_error`` contract)."""
    if uri.endswith(".f64"):
        if len(body) != c * 8:
            raise PermanentInputError(
                f"{uri}: declared C={c} (={c * 8} bytes) but object is {len(body)} bytes"
            )
        vec = np.frombuffer(body, dtype=_F64)
    elif uri.endswith(".csv"):
        try:
            lines = body.decode("ascii").split()
            vec = np.array([float(line) for line in lines], dtype=np.float64)
        except (UnicodeDecodeError, ValueError) as exc:
            raise PermanentInputError(f"{uri}: unparseable CSV: {exc}") from exc
        if vec.shape[0] != c:
            raise PermanentInputError(
                f"{uri}: declared C={c} but file has {vec.shape[0]} values"
            )
    else:
        raise PermanentInputError(
            f"{uri}: unknown input extension (accepted: .csv, .f64) — DM-005"
        )
    if not np.all(np.isfinite(vec)):
        raise NumericsError(f"{uri}: input contains non-finite values")
    return vec


def parse_partial(uri: str, body: bytes, *, c: int) -> np.ndarray:
    """Decode one of our own partial objects (always raw .f64 of length C)."""
    if len(body) != c * 8:
        raise PermanentInputError(
            f"{uri}: partial should be {c * 8} bytes (C={c}), got {len(body)}"
        )
    return np.frombuffer(body, dtype=_F64)


def encode_partial(vec: np.ndarray) -> bytes:
    return np.ascontiguousarray(vec, dtype=_F64).tobytes()


def encode_result(vec: np.ndarray) -> bytes:
    """The result file: one value per line, full float64 round-trip precision."""
    return ("\n".join(repr(float(x)) for x in vec) + "\n").encode("ascii")


def sum_vectors(vectors: list[np.ndarray]) -> np.ndarray:
    acc = np.zeros_like(vectors[0])
    for vec in vectors:
        np.add(acc, vec, out=acc)
    if not np.all(np.isfinite(acc)):
        raise NumericsError("accumulated sum contains non-finite values")
    return acc


class Executor:
    """Dispatch on payload kind; return the ``TaskResult`` T2 commits."""

    def __init__(self, store: BlobStore, *, speed_factor: float) -> None:
        if speed_factor < 1.0:
            raise ValueError(f"speed_factor must be >= 1.0, got {speed_factor}")
        self._store = store
        self._speed_factor = speed_factor

    def execute(self, task: ClaimedTask) -> TaskResult:
        started = time.monotonic()
        payload = task.payload
        if isinstance(payload, MapPayload):
            result = self._map(task.id, payload)
        elif isinstance(payload, ReducePayload):
            result = self._reduce(task.id, payload)
        elif isinstance(payload, FinalizePayload):
            result = self._finalize(payload)
        else:  # pragma: no cover — parse_payload makes this unreachable
            raise PermanentInputError(f"unknown payload type {type(payload)}")
        slowdown = (time.monotonic() - started) * (self._speed_factor - 1.0)
        if slowdown > 0:
            time.sleep(slowdown)
        return result

    def _map(self, task_id: str, p: MapPayload) -> TaskResult:
        vectors = [
            parse_input(uri, self._store.get(uri), c=p.c) for uri in p.input_uris
        ]
        acc = sum_vectors(vectors)
        uri = f"s3://{getattr(self._store, 'bucket', '')}/{partial_key(p.job_id, task_id)}"
        self._store.put(uri, encode_partial(acc), job_id=p.job_id)
        return TaskResult(output_uri=uri, count=len(p.input_uris))

    def _reduce(self, task_id: str, p: ReducePayload) -> TaskResult:
        vectors = [
            parse_partial(uri, self._store.get(uri), c=p.c) for uri in p.partial_uris
        ]
        acc = sum_vectors(vectors)
        uri = f"s3://{getattr(self._store, 'bucket', '')}/{partial_key(p.job_id, task_id)}"
        self._store.put(uri, encode_partial(acc), job_id=p.job_id)
        # count = Σ input counts is stamped by T2 from the consumed partials'
        # rows (the DB is authoritative); the executor only moves bytes.
        return TaskResult(output_uri=uri, count=None)

    def _finalize(self, p: FinalizePayload) -> TaskResult:
        total = parse_partial(p.partial_uri, self._store.get(p.partial_uri), c=p.c)
        mean = total / float(p.f)
        if not np.all(np.isfinite(mean)):
            raise NumericsError("final mean contains non-finite values")
        uri = f"s3://{getattr(self._store, 'bucket', '')}/{result_key(p.job_id)}"
        self._store.put(uri, encode_result(mean), job_id=p.job_id)
        return TaskResult(output_uri=uri, count=None)
