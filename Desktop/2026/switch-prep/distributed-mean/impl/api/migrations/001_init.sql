CREATE TYPE job_status  AS ENUM ('pending','running','finalizing','completed','failed');
-- 'finalizing' guards double-finalize: the completion branch of T2 transitions
-- running → finalizing atomically with enqueuing the finalize task (DM-003).
CREATE TYPE task_status AS ENUM ('pending','claimed','done','dead');
-- There is no transient 'failed' task state: a retryable failure IS a requeue to
-- 'pending' (T4), so failure and redelivery share one code path (DM-006).
CREATE TYPE task_type   AS ENUM ('map','reduce','finalize');
-- Three types. Inputs pre-exist at node-owned URIs (00 §Setting, 01 A-2), so there is
-- no generation task and no task type that creates data.

CREATE TABLE jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  f             INT  NOT NULL CHECK (f BETWEEN 2 AND 99999),
  c             INT  NOT NULL CHECK (c BETWEEN 2 AND 999999),
  status        job_status NOT NULL DEFAULT 'pending',
  idempotency_key TEXT,                        -- from the POST /jobs header; NULL allowed
  result_uri    TEXT,
  error         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_jobs_idem ON jobs (idempotency_key)
  WHERE idempotency_key IS NOT NULL;           -- partial: absent header ⇒ distinct job

CREATE TABLE tasks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id        UUID NOT NULL REFERENCES jobs(id),
  type          task_type   NOT NULL,
  status        task_status NOT NULL DEFAULT 'pending',
  priority      SMALLINT    NOT NULL,          -- finalize=0 < reduce=1 < map=2
  CHECK (priority = CASE type WHEN 'finalize' THEN 0 WHEN 'reduce' THEN 1
                              WHEN 'map'      THEN 2 END),
                                               -- makes the ASC/DESC footgun unrepresentable:
                                               -- priority is a function of type, not a free field.
                                               -- The CASE is exhaustive over task_type, so a new
                                               -- type cannot be inserted without pricing it
  payload       JSONB       NOT NULL,          -- see §2 (URIs + params only, < 1 KB)
  attempts      SMALLINT    NOT NULL DEFAULT 0,
  max_attempts  SMALLINT    NOT NULL DEFAULT 3,  -- finalize rows are seeded with 10 (§4 T3)
  worker_id     TEXT,
  lease_token   UUID,                          -- per-claim fencing token (DM-006)
  claimed_at    TIMESTAMPTZ,                   -- set by the claim query from the DB's now()
  deadline_at   TIMESTAMPTZ,                   -- claimed_at + TASK_DEADLINE_SECONDS (§8);
                                               -- absolute, never extended by a heartbeat
  lease_expires_at TIMESTAMPTZ,
  last_error    TEXT,                          -- last executor exception, recorded by T4;
                                               -- carries the offending input URI when a
                                               -- map task dies on an unreadable input
                                               -- There is no dedupe_key column: no task type
                                               -- spawns another, so no natural key is needed.
                                               -- map tasks are created exactly once, inside
                                               -- T1's single transaction; reduce dedupe comes
                                               -- from the consumed-guard, finalize's from the
                                               -- running→finalizing CAS (DM-006)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ
);
-- The queue index: everything the claim query touches, nothing else.
CREATE INDEX idx_tasks_claim ON tasks (status, priority, created_at) WHERE status = 'pending';
CREATE INDEX idx_tasks_lease ON tasks (lease_expires_at) WHERE status = 'claimed';
CREATE INDEX idx_tasks_inflight ON tasks (job_id) WHERE status = 'claimed';  -- the inflight CTE
CREATE INDEX idx_tasks_job   ON tasks (job_id, status);

CREATE TABLE partials (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id        UUID NOT NULL REFERENCES jobs(id),
  uri           TEXT NOT NULL,                 -- s3://…/partials/{producing_task_id}.f64
  count         INT  NOT NULL,                 -- n: input files covered by this Σ-vector
  produced_by   UUID NOT NULL UNIQUE REFERENCES tasks(id),  -- + ON CONFLICT DO NOTHING:
                                                            -- a redelivered task cannot
                                                            -- insert its partial twice (DM-006)
  consumed_by   UUID REFERENCES tasks(id),     -- NULL = available for pairing
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_partials_avail ON partials (job_id) WHERE consumed_by IS NULL;

CREATE TABLE workers (
  id             TEXT PRIMARY KEY,             -- hostname:pid
  status         TEXT NOT NULL DEFAULT 'idle', -- idle | busy | draining
  current_task   UUID,
  speed_factor   REAL NOT NULL DEFAULT 1.0,    -- demo: artificial slowdown for straggler tests
  last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE system_config (
  key TEXT PRIMARY KEY, value JSONB NOT NULL   -- {'desired_workers': 8}
);

CREATE TABLE events (                          -- append-only, feeds SSE (DM-009)
  id BIGSERIAL PRIMARY KEY,                    -- SSE Last-Event-ID cursor. Ids are ASSIGNED
                                               -- monotonically but COMMIT order is not id
                                               -- order: a slow txn's lower id becomes visible
                                               -- after a fast txn's higher id. So the SSE
                                               -- ticker reads with a visibility lag —
                                               -- `WHERE id > $cursor AND ts < now() - interval
                                               -- '1 second'` — and that lag IS the resume
                                               -- guarantee (DM-009). Rolled-back inserts leave
                                               -- permanent id gaps; gaps are normal.
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  type TEXT NOT NULL,                          -- taxonomy in DM-009 (job.* streamed; task.* folded into 1 Hz snapshot)
  job_id UUID, task_id UUID, worker_id TEXT,
  payload JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX ON events (id) INCLUDE (type);
CREATE INDEX ON events (job_id, id);
CREATE INDEX ON events (ts) WHERE type = 'task.done';   -- the 10 s throughput gauge (DM-009):
                                               -- the (id) index cannot serve a ts predicate
-- Retention: trim to 7 days / 2M rows; no UPDATE/DELETE otherwise.
