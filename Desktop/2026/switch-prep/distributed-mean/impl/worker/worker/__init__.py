"""Distributed Mean worker.

Implements the worker half of the system specified in ``docs/03-lld.md``:

* ``claim``      — LLD §3 claim query (queue + fairness in one statement)
* ``heartbeat``  — LLD §3 fenced lease extension, on its own connection
* ``executors``  — LLD §5 map / reduce / finalize bodies
* ``commit``     — LLD §4 T2 (fenced commit + eager pairing + completion)
* ``failure``    — LLD §4 T4 (executor failure → fenced requeue-or-dead)
* ``pairing``    — the pure decision function T2's pairing step executes
* ``blobstore``  — LLD §5/§7 read allow-list + write prefix confinement
"""

__all__ = [
    "blobstore",
    "claim",
    "commit",
    "config",
    "errors",
    "executors",
    "failure",
    "heartbeat",
    "pairing",
    "types",
]
