# ITD: DM-008 — Worker Pool Shape and W Configurability

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-002 (pull-based claiming, eager pairing), DM-004 (Postgres queue), DM-006 (leases, at-least-once, reaper), DM-007 (multi-job fairness), DM-009 (observability/UI), `../02-hld.md`, `../CONTEXT-BRIEF.md`

---

## Problem Statement

The fleet has to execute ≈25k compute **tasks** plus ≈2k `generate` tasks for a single max **job**
(F=100k, C=1M), where each leaf `map` task consumes up to **K**=5 inputs of 8 MB each and emits one
8 MB **partial**. Two things must be decided: (1) what a **worker** *is* as an OS-level artifact —
process, thread in a pool, or coroutine on an event loop — and (2) how **W**, the system-level worker
count, is set and changed. The brief permits W to be a constant; the bonus asks for it to be
configurable via the API. Target: `PATCH /system/workers {desired}` takes effect with actual converging on
desired within 15 s locally (≤90 s on ECS Fargate), a scale-down loses **zero** in-flight task work,
and a `kill -9` of one worker requeues exactly one task. Today there is no worker process at all —
this ITD defines it.

---

## Context

- **K=5 is stated as a RAM simulation.** It bounds the *fan-in of a task*, not the byte footprint of
  a container. Our `map` implementation streams the 5 CSV inputs one at a time into a single
  float64 accumulator of length C, so peak resident is ~1 accumulator (8 MB) + one file's parse
  buffers (a 1M-line CSV is ≈19 MB of text, ~40 MB transient in pandas' C engine), not 5×8 MB. Real
  per-worker RSS at C=1M lands around 150 MB including the CPython+numpy baseline.
  Stated canonically (A-8): **K=5 is a logical fan-in limit on how many files' worth of data a task
  may have in flight; we honour the stricter byte reading too by streaming.** `generate` is exempt
  from K because it writes files sequentially and aggregates nothing; under the stricter reading of K as
  covering writes, `GEN_BATCH` drops from 50 to 5 and the generate-task count rises 10× (≈2,000 →
  ≈20,000 for the max job), changing nothing structurally — this knob exists precisely so the
  disagreement is a config value, not a redesign.
- **Workers process files at different speeds** (given). The straggler answer is DM-002: pull-based
  claiming (D4) plus eager pairing (D3). Nothing is pushed to a named worker, so a slow worker
  simply claims fewer tasks. The worker model must not undermine this — in particular a worker must
  never hold a task it cannot finish.
- **Every state transition is transactional** against the Postgres `tasks` table, which *is* the
  queue (D5). Claiming is `FOR UPDATE SKIP LOCKED` with the fairness ordering from DM-007. Commit of
  a partial and the eager-pairing enqueue happen in one transaction (D3) — so the worker needs a
  real DB connection per worker, and connection count scales with W.
- **Leases, not assignments** (D7/DM-006). A claimed task carries `lease_expires_at`; the worker
  extends it by heartbeat while executing; a reaper requeues expired leases. Tunables (heartbeat
  10 s, lease 30 s, reaper sweep 5 s → worst-case detection 35 s) are owned by DM-006 and quoted
  here, not redefined.
- **Deployment is the same containers twice** (`../02-hld.md`): docker-compose locally
  (API, Postgres 16, MinIO, W× Python workers, supervisor, UI), ECS Fargate on AWS (API service +
  worker service, RDS, S3, ALB). Whatever sets W must have a local and an AWS implementation.
- **The demo has to make heterogeneity visible.** W is therefore a *stability* requirement for v1,
  not just a bonus: to show that a slow worker doesn't stall a job, W must be held where the operator
  put it.

---

## Alternatives

Two coupled axes: **how W is controlled**, and **what a worker is internally**.

### Axis 1 — Fixed W baked into the compose file

`docker-compose.yml` declares `deploy.replicas: 4`. Changing W means editing the file and
re-running compose. No API surface, no supervisor, no `desired_workers` row.

**Pros:**
- Zero moving parts; explicitly permitted by the brief ("free to keep them constant").
- No docker socket mount, no IAM policy, no reconciliation bug class at all.
- Removes an entire failure mode: desired and actual can never disagree, so the UI has one number.

**Cons:**
- Forfeits the stated bonus.
- Forfeits the most persuasive live demo beat: setting W=0, watching queue depth climb with the job
  visibly stalled, then W=4 and watching the backlog drain (≈27k tasks at the max-job envelope; a
  few hundred on the F=1000 demo job, which is what actually drains on screen).
- W becomes a deploy-time constant, so any future elasticity work starts from scratch rather than
  from a `desired_workers` value that already exists.

### Axis 1 — Supervisor reconciliation loop **[CHOSEN]**

`PATCH /system/workers {desired}` validates and writes `desired_workers` to a `system_config` row and emits a
`config.desired_workers_changed` event. A separate one-file supervisor container polls that row every
5 s and, only on change, issues the platform call: `docker compose up -d --scale worker=W` locally,
`ecs:UpdateService --desired-count W` on AWS.

**Pros:**
- One knob, two backends, identical semantics — the API never learns what a container is.
- Desired state lives in the DB, so it survives supervisor restarts and is queryable by the UI for
  free (DM-009) alongside actual.
- Idempotent and fail-static: if the supervisor dies, running workers keep claiming and committing;
  only *tracking* stops. The supervisor is off the critical path of every job.
- On AWS the platform is already a reconciler, so the supervisor shrinks to a translation shim.

**Cons:**
- Locally it needs `/var/run/docker.sock` mounted, which is root-equivalent on the host. Acceptable
  in a laptop demo; would need a proper control plane in anything real.
- Convergence is eventual and visibly so: ~1 s per container locally, 30–60 s for a Fargate task to
  reach RUNNING. The UI must show the transient gap rather than pretend it doesn't exist.
- `ecs:UpdateService` is rate-limited, so rapid API edits must be debounced — extra logic that only
  exists because the knob is live.

### Axis 1 — Workers manage their own population

Each worker reads `desired_workers`, and if `actual > desired` some worker self-terminates; if
`actual < desired` some worker spawns a sibling.

**Pros:**
- No supervisor container, no docker socket in a separate component, no ECS coupling.
- Scale-down can be *self-selected*: the worker that is idle volunteers, so no in-flight task is
  ever interrupted.

**Cons:**
- Bootstrap paradox: at W=0 there is nobody to spawn the first worker, so an external starter is
  needed anyway — the supervisor comes back through the side door.
- Scale-down is a distributed election over a shared counter. Without a lock, N workers all read
  `actual=8, desired=4` and four-plus of them exit; with a lock, we have written a worse supervisor
  inside the data plane.
- A worker that can spawn processes on its host is a worker that can fork-bomb it, and it inherits
  the docker socket into every replica instead of one component.

### Axis 1 — Autoscale on queue depth (KEDA / ECS target tracking)

Scale W from a signal: pending task count, or oldest-pending-task age, target-tracked.

**Pros:**
- The correct production answer. Cost follows load, W needs no human, and it composes with DM-007's
  fairness ordering because it reacts to aggregate depth, not per-job depth.
- Off-the-shelf on both platforms (KEDA Postgres scaler; ECS target tracking on a custom CloudWatch
  metric the API already has the numbers for).

**Cons:**
- Answers a different question than the bonus asks. The bonus is "keep W configurable via the API" —
  i.e. *user-set*. An autoscaler makes W an output, not an input, so the API knob becomes advisory.
- Actively destroys the demo: the moment a slow worker causes queue depth to rise, the autoscaler
  adds workers and masks exactly the straggler behaviour DM-002 exists to show.
- Needs tuning (cooldowns, step sizes, thrash suppression) that cannot be validated in a
  single-laptop run, so it would ship untested.

### Axis 2 — One OS process per worker **[CHOSEN]**

The container's entrypoint is a single Python 3.12 process running one loop: claim → heartbeat →
execute → commit. `W` containers ⇒ `W` processes ⇒ `W` rows in the `workers` table. A small daemon
thread inside the process extends the lease every 10 s while the main thread does numpy work.

**Pros:**
- True parallelism with no GIL reasoning required, and the heartbeat thread still gets scheduled
  during compute because numpy's `add` and `fromfile` and pandas' CSV parse loop all release the GIL.
- Crash blast radius is exactly one lease. A numpy segfault or an OOM kill costs one requeued task
  (≤35 s of latency: 30 s lease + 5 s reaper sweep, DM-006), not N.
- 1:1 with the W abstraction: "scale to W" is one number on one axis. `docker compose --scale` and
  ECS desired-count both speak this natively.
- K=5 accounting stays trivially per-worker, matching how the brief states the constraint.

**Cons:**
- ~150 MB RSS per worker of which ~100 MB is interpreter + numpy baseline, duplicated W times. At
  W=8 that is ~1.2 GB for ~400 MB of useful buffers.
- One DB connection per worker; W=32 plus API replicas starts to matter for RDS `max_connections`
  and would want pgbouncer.
- No overlap between the S3 GET of the next input and the summation of the current one, unless
  added inside the task (see below).

### Axis 2 — Thread pool inside one process

One container, T worker threads each claiming and executing tasks independently. W = containers × T.

**Pros:**
- Honestly cheap: the interpreter and numpy are paid once, and threads share the import cost. At
  T=8 this is ~250 MB total versus ~1.2 GB.
- The GIL objection is weaker than it first appears — the hot paths (`np.add` on float64 arrays,
  `np.fromfile`, the pandas C parser) all drop the GIL, so throughput would be close to processes.
- One `workers` row and one heartbeat per container: less DB chatter.

**Cons:**
- Blast radius is T. A segfault in a native extension or a container OOM kill drops T leases at
  once, so a single fault turns into T requeues and a T-task latency spike.
- W stops being one number. "Scale to W" becomes container-count × threads-per-container, two knobs
  for one API field, and the supervisor has to decide how to factor W — which is a policy nobody
  asked for.
- The K=5 RAM story blurs: the honest reading is T×5 logical inputs resident in one address space.
  Because we stream, the real figure is T×~50 MB rather than T×40 MB of inputs, but the simulated
  constraint stops mapping cleanly onto the unit the brief describes.

### Axis 2 — Single process, asyncio event loop

One process, N concurrent coroutines; `await` on S3 GETs and on Postgres via asyncpg.

**Pros:**
- The best fit for the I/O half of the work: a `map` task pulls 5×8 MB and pushes 8 MB, and
  overlapping those with compute is a genuine win.
- Cheapest possible concurrency for the claim/heartbeat/commit path, which is almost entirely waiting
  on the DB.

**Cons:**
- The compute half is CPU-bound numpy that blocks the loop, so heartbeats and every other coroutine
  stall for the duration of a summation. The fix is `run_in_executor`, i.e. threads or processes
  again, with an async wrapper on top — ceremony without a new capability.
- Debuggability regresses: a wedged coroutine is far harder to attribute than a wedged PID that
  `docker stats` and `py-spy` can point at.
- Does not remove the need to choose Axis 2 — it defers it.

### Axis 2 — Hand the fleet to Celery / RQ / Ray

Use an off-the-shelf Python task framework for the worker loop, retries, and concurrency.

**Pros:**
- Batteries included: prefetch, retries, visibility timeouts, autoscaling, a monitoring UI (Flower)
  that would partly satisfy the DM-009 bonus for free.
- Battle-tested worker lifecycle, including graceful shutdown, which we would otherwise write.

**Cons:**
- Brings its own broker (Redis/RabbitMQ), which duplicates the Postgres queue (D5) and reintroduces
  exactly the dual-write bug D5 exists to eliminate — eager pairing (D3) *requires* claim-and-enqueue
  in one transaction with the partial commit, and no external broker can join that transaction.
- Its own task-result backend competes with the `tasks` table for "single source of truth", so job
  completion (a critical aspect in the brief) would be inferred from two stores.
- The distribution algorithm — claim ordering, adaptive fan-in, fairness (D3/D8) — is the thing being
  evaluated. Hiding it inside another scheduler's prefetch logic forfeits the deliverable.

---

## Chosen: Process-per-worker, W reconciled by a supervisor from an API-written `desired_workers`

**The decision (D10).** A worker is one Python 3.12 process in one container running one loop:
claim → heartbeat → execute → commit, every transition transactional against Postgres. Each worker
inserts a row into `workers` at startup and heartbeats into it. W is a live system-level setting:
`PATCH /system/workers {desired}` validates `0 ≤ W ≤ W_max` (32), writes `system_config.desired_workers`, and
emits an event; a supervisor container polls the row every 5 s and, only on change, issues
`docker compose up -d --scale worker=W` locally or `ecs:UpdateService --desired-count W` on AWS.

**Positive case.** The pull loop is the whole straggler answer made concrete: a worker asks for work
only when it has none, so "workers process files at different speeds" needs no scheduler modelling of
speed — fast workers do more claims, and DM-002's eager pairing keeps the reduce forest collapsing
without waiting on the slowest branch. Process-per-worker makes W an honest count of an OS-visible
thing, which is why one integer suffices on both platforms and why the failure model stays a
one-liner: a dead worker = one expired lease = one requeue. Putting `desired_workers` in the DB
rather than in the supervisor's memory means the API, the supervisor, and the UI all read the same
row, so DM-009 gets desired-vs-actual for free.

**Graceful scale-down (drain semantics).** Scale-down is the interesting direction, and note we do
*not* choose the victim — compose and ECS do. So drain must be safe for an arbitrary victim:
SIGTERM sets a `draining` flag and returns immediately; the loop finishes the current task, commits
it (including any eager-pairing enqueue), marks its `workers` row `gone`, and exits 0. It does not
claim again. The lease is never abandoned: abandoning would still be *correct* (the reaper requeues
within 35 s) but would throw away real numpy work — a `generate` task writing 50 files × 8 MB is the
long pole. This is bounded by the platform's grace period: compose `stop_grace_period` and ECS
`StopTimeout` (max 120 s) are set to 120 s, and any task exceeding that degrades to the lease path
rather than to data loss. Correctness never depends on the drain completing; only efficiency does.

**Desired vs actual, surfaced.** The UI (DM-009) reads three numbers, not one: `desired` from
`system_config`; `actual` = `workers` rows with `last_heartbeat > now() − 3×10 s`, bucketed
`idle` / `busy` (busy ⇔ `current_task IS NOT NULL`) / `draining`; and the resulting gap rendered
as `reconciling…`. The `workers` row also carries `tasks_completed` and `started_at`, so per-worker
throughput is derivable — which is how heterogeneity becomes visible on screen. For a reproducible
demo, worker heterogeneity is injected by env var (`SPEED_FACTOR`) rather than hoped for.
Stale rows are marked `gone` by the same reaper that expires leases (DM-006) — one sweeper, two
responsibilities, no extra process.

**Why each rejection.** *Fixed W* is legitimate and the brief allows it, but it costs the bonus and
the W=0 → W=4 demo beat, and leaves no `desired_workers` for later elasticity to build on. *Worker
self-management* cannot bootstrap from W=0 and turns scale-down into an election over a shared
counter — a worse supervisor, embedded in the data plane, with the docker socket in every replica.
*Queue-depth autoscaling* is the right production answer and is documented as the evolution, but it
inverts the bonus (W becomes an output, not a user input) and would hide the straggler behaviour that
DM-002 is evaluated on. *Thread pool* is the strongest Axis-2 contender and the GIL argument against it
is genuinely weak given numpy releases it; it loses on blast radius (T leases per fault) and on
turning W into two knobs. *asyncio* wins on the I/O overlap but blocks the loop on the numpy add and
ends up delegating to threads anyway — and we keep its actual benefit by prefetching the next input
inside a task, which needs no change to W semantics. *Celery/Ray* cannot join D3's
claim-and-enqueue transaction and would hide the algorithm the brief asks for inside someone else's scheduler.

**Failure condition.** Revisit when any of: (a) W needs to respond to load rather than to a human —
i.e. we start owning a latency or cost SLO instead of demonstrating behaviour — at which point
`desired_workers` becomes the autoscaler's output and Axis 1 flips to KEDA/target-tracking;
(b) worst-case single-task duration exceeds the 120 s stop grace, so drains stop completing and every
scale-down costs a requeue — then tasks must be split finer or made checkpointable; (c) C rises far
enough that 5 inputs plus one accumulator no longer fit a container (≈C > 30M at a 2 GB limit), which
breaks K=5 as a task-level constraint and forces chunked/streaming `map` tasks; (d) W_max needs to
exceed ~32, where per-worker DB connections start pressing RDS `max_connections` and pgbouncer plus
`ecs:UpdateService` throttling become real.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Scale-up via API | `PATCH /system/workers {desired: 8}` from 4 → actual==8 within 15 s locally | UI desired/actual counters; `SELECT count(*) FROM workers WHERE last_heartbeat > now()-'30s'` |
| Scale-up on ECS | desired-count change → actual==desired within 90 s | ECS service events vs `workers` table |
| Graceful scale-down | 8 → 4 mid-job: zero tasks requeued by the reaper | no `task.lease_expired` events in the drain window |
| Crash isolation | `kill -9` one worker → exactly 1 task requeued, others keep committing | reaper log + `events` rows |
| W=0 | queue depth grows, no component errors; W=4 then drains the job | UI queue-depth panel |
| Straggler absorption | one worker at `SPEED_FACTOR=5` still completes ≥1 task; job wall-clock within 1.25× of the homogeneous run | two F=1000 runs compared |
| Per-worker footprint | RSS < 512 MB at C=1M, K=5 | `docker stats` during a `map`-heavy phase |
| Bad input rejected | `PATCH /system/workers {desired: 10000}` → 400, `desired_workers` unchanged | API test |
