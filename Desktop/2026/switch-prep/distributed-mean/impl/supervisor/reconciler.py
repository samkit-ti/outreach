"""W reconciliation — the thermostat loop (DM-008).

Reads ``desired_workers`` from ``system_config`` and converges the running
worker-container count to it via the Docker API. Scale-down is polite:
SIGTERM with a grace window, so the worker finishes the task in its hands
(the lease is the backstop if it doesn't).

Demo-only trust model: this container mounts /var/run/docker.sock, which is
root-equivalent on the host (HLD §9). On AWS the identical loop calls
``ecs.updateService(desiredCount)`` instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from .config import Config

log = logging.getLogger("reconciler")

_DESIRED = "SELECT value FROM system_config WHERE key = 'desired_workers'"
_EVENT = """
INSERT INTO events (type, payload) VALUES ('config.desired_workers_changed', %(payload)s)
"""


def read_desired(conn: psycopg.Connection[Any], cfg: Config) -> int | None:
    with conn.cursor() as cur:
        cur.execute(_DESIRED)
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    value = row[0]
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        desired = value
    elif isinstance(value, dict):
        candidate = value.get("desired", value.get("desired_workers", value.get("value")))
        if not isinstance(candidate, int) or isinstance(candidate, bool):
            return None
        desired = candidate
    else:
        return None
    return max(0, min(cfg.worker_max, desired))


class DockerReconciler:
    def __init__(self, cfg: Config) -> None:
        import docker  # noqa: PLC0415 — optional dep; only the reconciler needs it

        self.cfg = cfg
        self.client = docker.from_env()
        self._last_desired: int | None = None

    def _workers(self) -> list[Any]:
        containers = self.client.containers.list(
            all=False, filters={"label": [f"{k}={v}" for k, v in self.cfg.worker_labels().items()]}
        )
        return sorted(containers, key=lambda c: c.attrs.get("Created", ""))

    def reconcile_once(self, conn: psycopg.Connection[Any]) -> None:
        desired = read_desired(conn, self.cfg)
        if desired is None:
            return
        workers = self._workers()
        actual = len(workers)
        if desired != self._last_desired:
            log.info("desired_workers=%d (actual=%d)", desired, actual)
            with conn.cursor() as cur:
                cur.execute(_EVENT, {"payload": json.dumps({"desired": desired, "actual": actual})})
            conn.commit()
            self._last_desired = desired
        if actual < desired:
            template = workers[0] if workers else None
            for _ in range(desired - actual):
                self._start_worker(template)
        elif actual > desired:
            # newest first; pinned stragglers (distinct dm.role) never match here
            for container in reversed(workers[: actual - desired] if desired == 0 else workers[desired:]):
                log.info("scaling down: SIGTERM %s (grace %ds)", container.name, self.cfg.worker_stop_grace_seconds)
                container.stop(timeout=self.cfg.worker_stop_grace_seconds)

    def _start_worker(self, template: Any | None) -> None:
        if template is not None:
            image = template.image.tags[0] if template.image.tags else template.image.id
            env_list = template.attrs["Config"].get("Env", [])
            networks = list(template.attrs["NetworkSettings"]["Networks"].keys())
            network = networks[0] if networks else self.cfg.worker_network
        else:
            image = self.cfg.worker_image
            env_list = [
                f"{key}={value}"
                for key in self.cfg.worker_env_keys
                if (value := __import__("os").environ.get(key)) is not None
            ]
            network = self.cfg.worker_network
        container = self.client.containers.run(
            image,
            detach=True,
            environment=env_list,
            network=network,
            labels=self.cfg.worker_labels(),
        )
        log.info("scaled up: started worker container %s", container.name)
