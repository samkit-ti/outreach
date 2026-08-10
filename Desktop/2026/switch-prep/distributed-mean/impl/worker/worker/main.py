"""The worker loop — LLD §5: claim → heartbeat(execute) → commit.

Two connections, by design (LLD §5, DM-004): ``work`` runs claim/T2/T4
transactions; ``beat`` belongs to the heartbeat thread. The heartbeat wraps
EXECUTE ONLY and is joined before T2 opens. SIGTERM drains: finish the task in
hand, commit, deregister, exit — with the lease as backstop if we're killed
rudely anyway (DM-008).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
from types import FrameType

import psycopg

from .blobstore import S3BlobStore
from .claim import claim
from .commit import commit_done_or_discard
from .config import WorkerConfig, load_config
from .errors import ConfigError
from .executors import Executor
from .failure import fail_task
from .heartbeat import Heartbeat

log = logging.getLogger("worker")

_REGISTER = """
INSERT INTO workers (id, status, speed_factor, last_heartbeat)
VALUES (%(id)s, 'idle', %(speed_factor)s, now())
ON CONFLICT (id) DO UPDATE
SET status = 'idle', speed_factor = EXCLUDED.speed_factor, last_heartbeat = now()
"""

_SET_STATUS = """
UPDATE workers SET status = %(status)s, current_task = %(task_id)s,
                   last_heartbeat = now()
WHERE id = %(id)s
"""

_DEREGISTER = "DELETE FROM workers WHERE id = %(id)s"


class Worker:
    def __init__(self, cfg: WorkerConfig) -> None:
        self.cfg = cfg
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.draining = False
        self.work = psycopg.connect(cfg.database_url, autocommit=False)
        self.beat_conn = psycopg.connect(cfg.database_url, autocommit=False)
        store = S3BlobStore(
            endpoint=cfg.s3_endpoint,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
            bucket=cfg.s3_bucket,
            region=cfg.s3_region,
            force_path_style=cfg.s3_force_path_style,
            allowlist=cfg.input_uri_allowlist,
            connect_timeout_s=cfg.blob_connect_timeout_s,
            read_timeout_s=cfg.blob_read_timeout_s,
            max_attempts=cfg.blob_max_attempts,
        )
        self.executor = Executor(store, speed_factor=cfg.speed_factor)

    def _request_drain(self, _signum: int, _frame: FrameType | None) -> None:
        log.info("SIGTERM: draining — will finish the task in hand and exit")
        self.draining = True

    def _set_status(self, status: str, task_id: str | None) -> None:
        with self.work.cursor() as cur:
            cur.execute(
                _SET_STATUS,
                {"status": status, "task_id": task_id, "id": self.worker_id},
            )
        self.work.commit()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._request_drain)
        signal.signal(signal.SIGINT, self._request_drain)
        with self.work.cursor() as cur:
            cur.execute(
                _REGISTER,
                {"id": self.worker_id, "speed_factor": self.cfg.speed_factor},
            )
        self.work.commit()
        log.info(
            "worker %s registered (speed_factor=%s)",
            self.worker_id,
            self.cfg.speed_factor,
        )

        while not self.draining:
            task = claim(self.work, self.cfg, self.worker_id)
            if task is None:
                self._set_status("idle", None)
                continue

            self._set_status("busy", task.id)
            log.info("claimed %s task %s (job %s)", task.type, task.id, task.job_id)
            heartbeat = Heartbeat(
                self.beat_conn,
                task_id=task.id,
                lease_token=task.lease_token,
                lease_seconds=self.cfg.lease_seconds,
                heartbeat_seconds=self.cfg.heartbeat_seconds,
            )
            try:
                with heartbeat:  # wraps EXECUTE ONLY (LLD §5)
                    result = self.executor.execute(task)
                # heartbeat joined; T2 may open now
                outcome = commit_done_or_discard(
                    self.work,
                    task,
                    result,
                    worker_id=self.worker_id,
                    k_fanin=self.cfg.k_fanin,
                )
                if not outcome.committed:
                    log.warning(
                        "task %s: lease was reaped mid-execution; work discarded "
                        "(idempotent PUT left in place)",
                        task.id,
                    )
                elif outcome.job_completed:
                    log.info("job %s COMPLETED (count==F proof held)", task.job_id)
            except Exception as exc:  # noqa: BLE001 — every executor error takes T4
                heartbeat.stop()
                self.work.rollback()
                new_status = fail_task(
                    self.work,
                    task_id=task.id,
                    lease_token=task.lease_token,
                    error=exc,
                )
                log.error("task %s failed (-> %s): %s", task.id, new_status, exc)

        self._set_status("draining", None)
        with self.work.cursor() as cur:
            cur.execute(_DEREGISTER, {"id": self.worker_id})
        self.work.commit()
        self.work.close()
        self.beat_conn.close()
        log.info("worker %s drained and deregistered", self.worker_id)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    try:
        cfg = load_config()
    except ConfigError as exc:
        log.error("refusing to start: %s", exc)
        return 2
    Worker(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
