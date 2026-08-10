"""BlobStore — the trust boundary between the worker and the object store.

LLD §5 and DM-005 give the two directions *different* guards, because the read
set is caller-supplied and the write set is ours:

* **READ** is permitted only for URIs whose ``s3://bucket/prefix`` appears in
  ``INPUT_URI_ALLOWLIST``, or which live in our own bucket (partials the tree
  produced). Re-checked here and not only at submit, because the object behind a
  URI can change between the two checks (LLD §2). Without this, ``inputUris[]``
  is an SSRF vector.
* **WRITE** is confined to ``jobs/{jobId}/``. A task cannot write outside its own
  job, so a bug cannot corrupt a sibling's partials and nothing we compute can
  land on a node's input keys (DM-005).

The client is configured so it **cannot hang**: ``connect_timeout=5s``,
``read_timeout=30s``, ≤3 attempts with jittered exponential backoff (LLD §8).
DM-006 calls this belt-and-braces with the absolute ``deadline_at``: the timeouts
stop the common case, the deadline bounds every case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlparse

from .errors import BlobStoreGuardError, PermanentInputError

S3_SCHEME: Final[str] = "s3://"


@dataclass(frozen=True, slots=True)
class ParsedUri:
    """An ``s3://bucket/key`` split into its two halves."""

    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"{S3_SCHEME}{self.bucket}/{self.key}"


def parse_s3_uri(uri: str) -> ParsedUri:
    """Split an ``s3://bucket/key`` URI. Raises on anything else.

    Rejects ``..`` segments outright: a key containing them can normalise out of
    its own prefix at some layer between here and the store, which would defeat
    the write confinement below by construction rather than by intent.
    """
    if not isinstance(uri, str) or not uri.startswith(S3_SCHEME):
        raise PermanentInputError(f"not an s3:// URI: {uri!r}")
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket:
        raise PermanentInputError(f"s3 URI names no bucket: {uri!r}")
    if not key:
        raise PermanentInputError(f"s3 URI names no key: {uri!r}")
    if parsed.query or parsed.fragment:
        raise PermanentInputError(f"s3 URI must carry no query or fragment: {uri!r}")
    if ".." in key.split("/"):
        raise PermanentInputError(f"s3 URI key contains a '..' segment: {uri!r}")
    return ParsedUri(bucket=bucket, key=key)


def job_prefix(job_id: str) -> str:
    """The only prefix a task of ``job_id`` may write under (LLD §7)."""
    if not job_id or "/" in job_id:
        raise BlobStoreGuardError(f"invalid job id for a write prefix: {job_id!r}")
    return f"jobs/{job_id}/"


def partial_key(job_id: str, task_id: str) -> str:
    """``jobs/{jobId}/partials/{taskId}.f64`` — LLD §7.

    Derived from the *task id*, never from the attempt number: that is what makes
    a retry write byte-identical content to the same key (DM-006 property 1).
    """
    if not task_id or "/" in task_id:
        raise BlobStoreGuardError(f"invalid task id for a partial key: {task_id!r}")
    return f"{job_prefix(job_id)}partials/{task_id}.f64"


def result_key(job_id: str) -> str:
    """``jobs/{jobId}/result.csv`` — LLD §7.

    Job-derived rather than task-derived, which is safe only because exactly one
    finalize task exists per job (the ``running → finalizing`` CAS, DM-003).
    """
    return f"{job_prefix(job_id)}result.csv"


def is_read_allowed(
    uri: str, *, allowlist: tuple[str, ...], own_bucket: str
) -> bool:
    """Whether ``uri`` may be READ (LLD §5, DM-005).

    Allowed if it matches an ``INPUT_URI_ALLOWLIST`` entry, or if it is in our
    own bucket (reduce and finalize read partials the tree produced).

    Prefix matching is done on ``(bucket, key-prefix)`` after parsing, not on the
    raw string: a naive ``uri.startswith(entry)`` would let
    ``s3://distributed-mean-evil/x`` match an allow-list entry of
    ``s3://distributed-mean/``.
    """
    try:
        target = parse_s3_uri(uri)
    except PermanentInputError:
        return False
    if target.bucket == own_bucket:
        return True
    for entry in allowlist:
        remainder = entry[len(S3_SCHEME) :]
        entry_bucket, _, entry_prefix = remainder.partition("/")
        if target.bucket != entry_bucket:
            continue
        if entry_prefix == "" or target.key.startswith(entry_prefix):
            return True
    return False


def is_write_allowed(uri: str, *, job_id: str, own_bucket: str) -> bool:
    """Whether ``uri`` may be WRITTEN by a task of ``job_id`` (LLD §5).

    Our bucket only, and only under ``jobs/{jobId}/``.
    """
    try:
        target = parse_s3_uri(uri)
    except PermanentInputError:
        return False
    if target.bucket != own_bucket:
        return False
    return target.key.startswith(job_prefix(job_id))


class BlobStore(Protocol):
    """The surface the executors use. Narrow on purpose, so tests can fake it."""

    def get(self, uri: str) -> bytes:
        """Read an object. Refuses URIs outside the read allow-list."""

    def put(self, uri: str, body: bytes, *, job_id: str) -> None:
        """Write an object. Refuses URIs outside ``jobs/{jobId}/``."""


class S3BlobStore:
    """``BlobStore`` over the S3 API (MinIO locally, S3 on AWS — LLD §9, DM-005)."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        force_path_style: bool,
        allowlist: tuple[str, ...],
        connect_timeout_s: int,
        read_timeout_s: int,
        max_attempts: int,
    ) -> None:
        # Imported here rather than at module scope so the guard helpers above —
        # which the unit tests exercise — need no boto3 installed.
        import boto3  # noqa: PLC0415
        from botocore.config import Config  # noqa: PLC0415

        self._bucket = bucket
        self._allowlist = allowlist
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                connect_timeout=connect_timeout_s,
                read_timeout=read_timeout_s,
                # 'adaptive' would add client-side rate limiting on top of the
                # retries; 'standard' is the bounded jittered-exponential policy
                # DM-006 asks for and nothing more.
                retries={"max_attempts": max_attempts, "mode": "standard"},
                s3={"addressing_style": "path" if force_path_style else "auto"},
            ),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def get(self, uri: str) -> bytes:
        if not is_read_allowed(uri, allowlist=self._allowlist, own_bucket=self._bucket):
            raise BlobStoreGuardError(
                f"read refused: {uri} is not in INPUT_URI_ALLOWLIST "
                f"{list(self._allowlist)} and not in our bucket {self._bucket!r}"
            )
        target = parse_s3_uri(uri)
        response = self._client.get_object(Bucket=target.bucket, Key=target.key)
        body = response["Body"]
        try:
            return bytes(body.read())
        finally:
            body.close()

    def put(self, uri: str, body: bytes, *, job_id: str) -> None:
        if not is_write_allowed(uri, job_id=job_id, own_bucket=self._bucket):
            raise BlobStoreGuardError(
                f"write refused: {uri} is outside jobs/{job_id}/ in bucket "
                f"{self._bucket!r}"
            )
        target = parse_s3_uri(uri)
        self._client.put_object(Bucket=target.bucket, Key=target.key, Body=body)
