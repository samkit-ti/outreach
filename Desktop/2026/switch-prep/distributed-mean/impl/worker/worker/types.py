"""Task payloads and results — LLD §2's discriminated union, as Python dataclasses.

LLD §2 defines the payload as a TS discriminated union "mirrored by Python
dataclasses". This module is that mirror, plus the parser that turns the JSONB
column into one of the three types. The parser is strict: an unknown ``kind``, a
missing field, or a chunk larger than ``K_FANIN`` raises rather than defaulting,
because a payload is the *entire* contract of a task (DM-006: "a map task's
inputUris ARE its identity") and a silently-repaired payload computes a
plausible wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from .errors import PermanentInputError

TaskType = Literal["map", "reduce", "finalize"]

#: LLD §1: ``priority = CASE type WHEN 'finalize' THEN 0 WHEN 'reduce' THEN 1
#: WHEN 'map' THEN 2 END``. A DDL CHECK enforces this, so the worker only ever
#: reads it — it is here so the reduce-task INSERT in T2 does not hardcode a 1.
PRIORITY_BY_TYPE: Final[dict[str, int]] = {"finalize": 0, "reduce": 1, "map": 2}

#: LLD §7: the two input encodings we accept, dispatched by extension (DM-005).
INPUT_EXTENSIONS: Final[tuple[str, ...]] = (".csv", ".f64")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise PermanentInputError(
            f"payload.{key} must be a non-empty string, got {value!r}"
        )
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    # bool is an int subclass; a JSON true here means a malformed payload.
    if isinstance(value, bool) or not isinstance(value, int):
        raise PermanentInputError(f"payload.{key} must be an integer, got {value!r}")
    if value < 1:
        raise PermanentInputError(f"payload.{key} must be >= 1, got {value}")
    return value


def _require_str_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise PermanentInputError(
            f"payload.{key} must be a non-empty array of strings, got {value!r}"
        )
    for item in value:
        if not isinstance(item, str) or item == "":
            raise PermanentInputError(
                f"payload.{key} must contain only non-empty strings, got {item!r}"
            )
    return tuple(value)


@dataclass(frozen=True, slots=True)
class MapPayload:
    """``{kind:'map', jobId, inputUris[≤5], c}`` — LLD §2."""

    kind: Literal["map"]
    job_id: str
    input_uris: tuple[str, ...]
    c: int


@dataclass(frozen=True, slots=True)
class ReducePayload:
    """``{kind:'reduce', jobId, partialIds[2–5], partialUris, c}`` — LLD §2."""

    kind: Literal["reduce"]
    job_id: str
    partial_ids: tuple[str, ...]
    partial_uris: tuple[str, ...]
    c: int


@dataclass(frozen=True, slots=True)
class FinalizePayload:
    """``{kind:'finalize', jobId, partialUri, f, c}`` — LLD §2."""

    kind: Literal["finalize"]
    job_id: str
    partial_uri: str
    f: int
    c: int


TaskPayload = MapPayload | ReducePayload | FinalizePayload


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """One row of the claim query's ``RETURNING`` clause (LLD §3).

    ``lease_token`` and ``deadline_at`` come back from the DB and are never
    computed here: every lease and deadline value in the system is written by a
    server-side ``now()`` expression (LLD §3).
    """

    id: str
    type: TaskType
    payload: TaskPayload
    lease_token: str
    job_id: str


@dataclass(frozen=True, slots=True)
class TaskResult:
    """What ``execute()`` returns for T2 to commit.

    ``output_uri`` is the object the executor PUT before returning; ``count`` is
    the number of *input files* the produced partial covers (``NULL`` for
    finalize, whose output is the result CSV rather than a partial). T2 writes
    both into the ``partials`` row or the ``jobs`` row respectively — the worker
    never derives either from anything but the task's own payload, which is what
    makes a retry byte-identical (DM-006).
    """

    output_uri: str
    count: int | None


def parse_payload(task_type: str, raw: dict[str, Any], *, k_fanin: int) -> TaskPayload:
    """Parse a ``tasks.payload`` JSONB value into its dataclass.

    ``task_type`` is the ``tasks.type`` enum from the same row. It must agree
    with ``payload.kind``: a row whose column and payload disagree is corrupt in
    a way no executor can safely guess at, so it fails rather than trusting one
    of the two.
    """
    if not isinstance(raw, dict):
        raise PermanentInputError(f"payload must be a JSON object, got {type(raw)}")
    kind = raw.get("kind")
    if kind != task_type:
        raise PermanentInputError(
            f"tasks.type={task_type!r} disagrees with payload.kind={kind!r}"
        )

    if kind == "map":
        input_uris = _require_str_list(raw, "inputUris")
        if len(input_uris) > k_fanin:
            raise PermanentInputError(
                f"map payload carries {len(input_uris)} inputUris, "
                f"exceeding K_FANIN={k_fanin} (the RAM constraint, LLD §8)"
            )
        if len(set(input_uris)) != len(input_uris):
            # A repeated URI would double-weight that vector (LLD §4 T1's
            # submit-time check). Re-checked here because the payload is what we
            # actually execute.
            raise PermanentInputError(
                f"map payload repeats an input URI, which would double-weight it: "
                f"{sorted(input_uris)}"
            )
        return MapPayload(
            kind="map",
            job_id=_require_str(raw, "jobId"),
            input_uris=input_uris,
            c=_require_int(raw, "c"),
        )

    if kind == "reduce":
        partial_ids = _require_str_list(raw, "partialIds")
        partial_uris = _require_str_list(raw, "partialUris")
        if len(partial_ids) != len(partial_uris):
            raise PermanentInputError(
                f"reduce payload has {len(partial_ids)} partialIds but "
                f"{len(partial_uris)} partialUris"
            )
        if not 2 <= len(partial_uris) <= k_fanin:
            # LLD §2: 2–5. Fan-in 1 is not a reduce (it would copy a partial and
            # invent a tree level); >5 breaks the RAM ceiling.
            raise PermanentInputError(
                f"reduce payload has fan-in {len(partial_uris)}, outside 2..{k_fanin}"
            )
        return ReducePayload(
            kind="reduce",
            job_id=_require_str(raw, "jobId"),
            partial_ids=partial_ids,
            partial_uris=partial_uris,
            c=_require_int(raw, "c"),
        )

    if kind == "finalize":
        f = _require_int(raw, "f")
        if f < 2:
            raise PermanentInputError(f"finalize payload has f={f}, must be >= 2")
        return FinalizePayload(
            kind="finalize",
            job_id=_require_str(raw, "jobId"),
            partial_uri=_require_str(raw, "partialUri"),
            f=f,
            c=_require_int(raw, "c"),
        )

    raise PermanentInputError(f"unknown payload kind {kind!r}")
