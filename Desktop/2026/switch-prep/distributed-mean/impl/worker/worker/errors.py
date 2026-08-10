"""Worker exception taxonomy.

Every exception here travels T4's single path (LLD §4 T4): fenced requeue to
``pending``, or straight to ``dead`` once ``attempts >= max_attempts``.

``PermanentInputError`` is *named* but deliberately **not shortcut**: DM-006's
failure matrix rejects classifying transient vs deterministic failures at the
worker, because a misclassifier that calls a transient 503 "permanent" fails a
multi-hour job needlessly. The subclass exists so that ``last_error`` can carry
the offending URI and, on a length mismatch, both the declared C and the length
found (LLD §2, §4 T4) — not so that the retry budget can be skipped.
"""

from __future__ import annotations


class WorkerError(Exception):
    """Base for every error raised inside ``execute()``."""


class ConfigError(WorkerError):
    """A required environment variable is missing or unparseable.

    Raised at process start, before any task is claimed. Not a task failure:
    there is no lease to fence and nothing to requeue, so this one kills the
    process rather than travelling T4.
    """


class BlobStoreGuardError(WorkerError):
    """A URI violated the read allow-list or the write prefix confinement.

    A guard violation is a bug in *our* code or an SSRF attempt through
    ``inputUris[]`` (DM-005). Either way the task cannot succeed, so it takes
    T4's path with the offending URI recorded.
    """


class PermanentInputError(WorkerError):
    """An input object is unreadable, mis-sized, or in an unknown format.

    No retry can change an object's length or its extension, so this is
    permanent in fact (DM-005, DM-006) — but it still consumes its three
    attempts via T4 rather than being special-cased into an early death.
    """


class NumericsError(WorkerError):
    """A computed vector contains a non-finite value, or ``count != F``.

    ``count == F`` at finalize time is the end-to-end checksum over the whole
    distributed execution (DM-006, DM-010): it fails loudly if any input vector
    was lost *or* counted twice. DM-010's failure condition 4 makes this the
    highest-priority signal in the system, so it is a distinct type.
    """
