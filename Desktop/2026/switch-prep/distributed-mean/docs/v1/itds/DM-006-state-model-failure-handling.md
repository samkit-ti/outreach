# ITD: DM-006 — Task State Model, Liveness, and Failure Handling

**Date:** 2026-08-09
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001, DM-002, DM-003, DM-004, DM-005, DM-007, DM-010, `../02-hld.md`, `../CONTEXT-BRIEF.md`

---

## Problem Statement

A max job (F=100k, C=1M) decomposes into ≈2k `generate` tasks plus ≈25k compute tasks
(20,000 leaf `map` tasks and ≈5,000 `reduce` tasks over ~7 tree levels), executed by W
heterogeneous workers pulling from a Postgres-backed queue. At that task count, worker
death is not an edge case: a 0.1% per-task failure rate loses ~25 tasks per job, and a
lost partial high in the reduce tree destroys the work of an entire subtree (a level-5
partial covers 5⁵ = 3,125 input files). The system must therefore (a) detect a dead or
hung worker without a human in the loop, (b) re-execute its task, and (c) guarantee that
re-execution cannot corrupt the answer — because the deliverable is an *exact* index-wise
mean, and a silently double-counted or silently dropped partial produces a plausible but
wrong 1M-element result file that no downstream consumer can detect. This ITD locks the
task state machine, the liveness mechanism, and the delivery semantics that make
re-execution safe.

---

## Context

Constraints and locked decisions this decision has to live inside:

- **K = 5 fan-in** (the RAM constraint) means work is decomposed into many small tasks
  rather than few large ones. Small tasks are cheap to retry (a `map` task reads 5 × 8 MB
  and sums 5M float64 — seconds of work), which is what makes restart-on-failure viable
  instead of mid-task checkpointing.
- **D4 / pull-based distribution (DM-002, DM-003).** Nothing is assigned to a named
  worker, so "worker X died, reassign its tasks" is not a lookup we can do from an
  assignment table — liveness has to be expressed on the *task*, not on the worker.
- **D5 / the `tasks` table is the queue (DM-004).** Every state transition is a Postgres
  transaction, so enqueue-and-transition is atomic. This is what makes the guards below
  possible; a separate broker plus a separate state store would reintroduce the dual-write
  bug that D5 exists to kill.
- **D6 / S3-API data plane (DM-005).** Bytes live in the object store; queue and DB carry
  URIs. Object writes are outside the DB transaction, so no DB transaction can ever cover
  "write 8 MB and mark task done" atomically. Idempotency, not atomicity, has to bridge
  that gap.
- **D3 / eager pairing (DM-002).** Reduce tasks are created inside the transaction that
  commits a partial, by atomically claiming 5 unconsumed partials. *Consumption is
  therefore an act of task creation, not an act of task execution* — a fact this ITD leans
  on heavily for the double-consume guard.
- **D2 / D12 (DM-001, DM-010).** Partials carry `(sum_vector, count)`; `finalize` divides
  by F exactly once. The invariant `count == F` at finalize time is an end-to-end checksum
  over the whole distributed execution: it fails loudly if any input file was lost *or*
  counted twice.

---

## Alternatives

### At-most-once delivery (fire and forget)

Worker claims a task, deletes it from the queue immediately, executes. If the worker dies,
the task is simply gone.

**Pros:**
- Simplest possible implementation: no leases, no reaper, no attempt counter, no
  idempotency requirement on task outputs.
- No duplicate execution ever, so no wasted compute and no need to reason about two
  workers running the same task concurrently.

**Cons:**
- Silently produces a wrong answer. A lost leaf `map` task means `finalize` sees
  count = 99,995 instead of 100,000; without the count check the result file is a mean over
  the wrong denominator, and *with* the count check the job simply fails after hours of
  work with no recovery path.
- The loss is disproportionate high in the tree: dropping one level-5 partial discards
  3,125 files' worth of already-completed work, which at 20,000 leaf tasks is ~15% of the
  job.
- Makes worker crashes a data-integrity event rather than a scheduling event, which means
  every deploy, every OOM, and every spot-instance reclaim is a correctness incident.

### Exactly-once via distributed transactions (2PC across queue and object store)

Coordinate the queue state change and the object-store write in a two-phase commit so that
"task done" and "output exists" are one atomic fact.

**Pros:**
- Would give the property everyone actually wants: no duplicates, no losses, no
  application-level reasoning about redelivery.
- Familiar and well-specified (XA-style) where all participants support it.

**Cons:**
- The object store is not a 2PC participant. S3 exposes no prepare/commit protocol, so the
  most important resource in the system cannot enlist. The best available approximation is
  write-then-mark plus compensation on abort — which is exactly at-least-once with extra
  steps.
- 2PC blocks on coordinator failure: an in-doubt transaction holds locks until the
  coordinator recovers. With ≈27k tasks per job and W workers, one wedged coordinator
  stalls the fleet, which is a worse liveness story than the crash it was protecting
  against.
- Adds a synchronous round-trip per task boundary to a workload whose tasks take seconds,
  so the coordination overhead is a visible fraction of task cost.
- "Exactly-once delivery" is not achievable across a network boundary anyway; the
  achievable property is exactly-once *effect*, which is what alternative 3 buys directly
  and far more cheaply.

### At-least-once delivery + idempotent task effects — **CHOSEN**

Accept that a task can execute more than once, and make a second execution
indistinguishable from the first: deterministic output object keys, atomic PUT, uniqueness
constraints on the rows a task inserts, and a fenced commit that lets a stale worker's work
be discarded harmlessly.

**Pros:**
- Delivers exactly-once *effect*, which is the property that actually protects the answer,
  without needing any protocol the object store does not support.
- The redundancy cost is bounded and tiny: a duplicated task wastes seconds of one worker's
  time, and duplicates only happen on crash or lease expiry.
- Failure handling collapses into one mechanism — "re-run the task" — for every failure
  mode below, instead of a per-failure-mode recovery routine.

**Cons:**
- Idempotency is a *design obligation on every task type*, enforced by review rather than
  by the runtime. Add a task type that appends to a log or increments a counter and the
  guarantee silently breaks.
- Duplicate execution is real: two workers can briefly run the same reduce task, doing the
  same 40 MB of reads. Wasteful, though bounded.
- Requires disciplined determinism (per-file seeds in `generate`, key derived from task id
  not attempt number), which constrains future task design.

### Worker liveness via a dedicated membership service (ZooKeeper / etcd sessions)

Workers hold ephemeral session nodes; the coordination service detects session loss and a
watcher requeues that worker's tasks.

**Pros:**
- Purpose-built failure detection with sub-second granularity — much faster than a 30 s
  lease, and the detection logic is battle-tested rather than hand-rolled.
- Gives group membership as a first-class primitive, which the W-reconciliation supervisor
  (D10, DM-008) and the UI worker roster (D11, DM-009) could also consume.
- Fencing tokens come for free and are monotonic, which is the textbook answer to the
  zombie-writer problem.

**Cons:**
- Adds a third stateful system (Postgres + object store + ZK/etcd) to a design whose whole
  case for a Postgres queue (D5) is that we already need the DB and should not multiply
  coordinators. That is a real operational cost: quorum sizing, disk, upgrade choreography.
- Session loss is not the same as task loss. We would still need per-task state in Postgres
  to know *which* tasks to requeue, so the membership service replaces the timeout but not
  the bookkeeping — and now liveness truth lives in one system while task truth lives in
  another, which is the split-brain shape we were avoiding.
- Faster detection buys us almost nothing here. Tasks take seconds and jobs take minutes to
  hours; shaving 30 s off crash detection is invisible against a 3.5 h max-job makespan.

### Mid-task checkpointing with resume

A worker periodically persists its running partial sum so that a crash resumes from the
last checkpoint instead of restarting the task.

**Pros:**
- Bounds wasted work on crash to the checkpoint interval rather than to the whole task —
  the right answer if tasks were long.
- Would let us raise K well above 5 later without making retries expensive.

**Cons:**
- Solves a problem K=5 already solved. A task's entire cost is seconds; a checkpoint of a
  C=1M running sum is 8 MB, so checkpointing even once per task can cost more I/O than
  re-running it.
- Introduces a second mutable location for in-flight task state, which must then be
  garbage-collected, versioned, and reconciled with the task row — new failure modes in
  exchange for savings we do not need.

---

## Chosen: At-least-once with idempotent effects, lease-based liveness, capped attempts

**The decision.** Task states are `pending → claimed → done | failed(retryable) | dead`.
A claim sets `lease_expires_at = now() + 30s` and a per-claim `lease_token`; the worker
heartbeats every 10 s to extend it; a reaper polls every 5 s and returns any task whose
lease has expired to `pending` with `attempts += 1`. Worst-case detection latency is
lease (30 s) + reaper poll (5 s) = 35 s. Delivery is at-least-once and every task output
is idempotent. After 3 attempts a task becomes `dead` and its job becomes `failed` with a
recorded cause.

**Why this is positively right, not merely least-bad.** Three properties do the work:

1. **Deterministic keys make re-execution a no-op.** A task's output object key is derived
   from the task id, never from the attempt number: `jobs/{job_id}/partials/{task_id}.f64`.
   Combined with a *pure* task body — a `map` task over a fixed set of 5 input files, a
   `reduce` task over a fixed set of partial ids, a `generate` task with per-file
   deterministic seeds (D9) — a retry writes byte-identical content to the same key. S3's
   PUT is atomic per object, so a concurrent reader sees either the previous complete object
   or the new complete object, never a torn one. Overwriting is therefore not a hazard to be
   managed; it is the mechanism.

2. **Uniqueness constraints make the metadata idempotent too.** The dangerous duplicate is
   not the 8 MB object, it is a second row in `partials` for the same task: two rows means
   the same sums and the same count are folded into the tree twice, which inflates `count`
   past F and corrupts the mean. A unique constraint on `partials(task_id)` with
   `INSERT … ON CONFLICT DO NOTHING` makes the second commit a no-op. Likewise, tasks
   created by a completing task carry a natural key
   (`UNIQUE (job_id, task_type, batch_index)` for `generate`-spawned `map` tasks) so a
   re-run generate cannot fork a duplicate subtree.

3. **A fenced commit lets us discard a zombie's work safely.** The commit transaction is
   `UPDATE tasks SET state='done' WHERE id = $t AND lease_token = $mine AND state='claimed'`.
   If it updates 0 rows the worker lost its lease while working (long GC pause, network
   partition, paused VM) and aborts without touching job state. Note what we did *not* need:
   a monotonic fencing token at the storage layer. Fencing tokens are required when the
   protected effect is non-idempotent; we made the effect idempotent, so a stale writer's PUT
   is benign by construction and only the *metadata* transition needs fencing — which the
   DB gives us for free.

**The double-consume guard for reduce tasks.** The sharpest race in the design: a `reduce`
task is redelivered after a lease expiry, so two workers hold it. If consuming input
partials happened at execution time, worker A could consume partials {p1…p5} and worker B
could consume a *different* set {p6…p10} under the same task id — and then one of those two
sets would be marked consumed by a task that never emits their sum, silently dropping
5 × 8 MB of work and making `count == F` unreachable. We remove the race rather than
serialize it: per D3, consumption happens **once, at reduce-task creation time**, inside the
same transaction that inserts the reduce task:

```sql
-- inside the transaction that commits a partial (D3, DM-002)
WITH claimed AS (
  UPDATE partials SET consumed_by_task_id = $new_reduce_task_id
  WHERE id IN (SELECT id FROM partials
               WHERE job_id = $job AND consumed_by_task_id IS NULL
               ORDER BY created_at LIMIT 5 FOR UPDATE SKIP LOCKED)
  RETURNING id)
INSERT INTO tasks (id, job_id, task_type, input_partial_ids, …)
SELECT $new_reduce_task_id, $job, 'reduce', array_agg(id), … FROM claimed;
```

The `consumed_by_task_id IS NULL` predicate under `FOR UPDATE` is the transactional guard:
a partial can be claimed by exactly one reduce task, ever. Consequently a redelivered reduce
task's input set is *immutable and identical* across attempts — both workers read the same
five partial ids, compute the same sum, and write the same key. Double-consume is not
prevented at execution time; it is made unrepresentable.

**Failure matrix.**

| Failure | What happens | Why it is safe |
|---|---|---|
| Worker crashes mid-task | Heartbeats stop; lease expires at ≤30 s; reaper requeues to `pending`, `attempts += 1`; another worker claims it | No partial output row was committed. Any bytes the dead worker had already PUT sit under the deterministic task-id key and are overwritten by the retry with identical content |
| Worker crashes **after** PUT, **before** commit | Task looks unstarted; it re-runs and re-PUTs the same key | Same key, same bytes — the write is idempotent. The `partials` row is inserted exactly once because the first attempt never committed one |
| Worker commits, then crashes before ACKing anything | Nothing to ack — the commit *is* the ack (one transaction covers `state='done'`, the partial row, and any eagerly-created reduce task) | D5's single-store property: there is no second system to fall out of sync with |
| Worker hangs / long GC / paused VM (zombie holding a lease) | Lease expires, task is requeued, two executors run concurrently for a while; the zombie's eventual commit fails the `lease_token` check and it discards its work | Fenced commit + idempotent PUT. Cost is duplicated compute, not corruption |
| Reaper crashes | Expired leases are simply not reclaimed until it restarts; nothing else degrades — claims, executions, and commits continue | Degraded liveness, never broken safety. The reaper is stateless and its action (`UPDATE … WHERE lease_expires_at < now()`) is idempotent, so we can run several instances with no leader election |
| Postgres unavailable | Workers cannot claim, cannot heartbeat, cannot commit → the fleet quiesces within one poll interval. On recovery, in-flight leases have expired and those tasks are requeued | Nothing is lost because every transition is a transaction: an interrupted transition rolls back whole. See "why pause is fine" below |
| Object store unavailable | Read or PUT raises; the worker marks the task `failed(retryable)` with the error, backing off 5 s then 10 s (exponential, jittered). Third failure → `dead` → job `failed` with cause | The data plane *is* the data. There is no correct way to continue without it, so failing loudly beats producing a mean over the files that happened to be readable |
| API process dies | Jobs and tasks are in the DB; the API is stateless (this is precisely why D1 rejected a central accumulator on the API). Workers keep draining the queue; SSE clients reconnect (D11, DM-009) | No job state lives in API memory |
| Poison task (deterministic bug, malformed input) | Fails identically 3 times, then `dead` → job `failed` with the recorded error | We deliberately do **not** classify transient vs deterministic failures. A misclassifier that calls a transient S3 blip "permanent" fails a 3.5 h job needlessly; three cheap attempts cost ≤3× a few seconds |
| Duplicate `generate` task | Re-generates the same files from the same per-file seeds (D9) → byte-identical files; its `map` tasks are re-inserted under `ON CONFLICT DO NOTHING` | Determinism turns input generation into just another idempotent effect |

**Why "pause is fine" when the DB is down.** This is a batch analytics job, not a serving
path: the SLO is job completion and correctness, not per-request availability. An RDS
multi-AZ failover is ~60–120 s; against a max job whose makespan is hours, that is under 1%
of wall clock, and it costs zero correctness. The alternative — workers buffering completed
task state locally and replaying it on reconnect — creates a second source of truth for task
state, i.e. exactly the dual-write hazard D5 was chosen to eliminate. Availability is the
right thing to trade away here, and we trade it away explicitly.

**Why max attempts = 3, and why a dead task fails the whole job.** A job's deliverable is
the exact index-wise mean over F files. If one leaf is permanently unprocessable, no correct
answer exists; emitting a mean over 99,995 files would be a silent lie in a 1M-element file
that no consumer can validate. So the job fails with a cause, and `finalize`'s
`assert count == F` (D2/D12, DM-010) is the last line of defence — it catches any lost *or*
double-counted work end-to-end, independent of everything above.

**How the `generate → map` dependency is handled (D9).** Input generation is distributed:
≈2,000 `generate` tasks × ~50 files. Their `map` tasks are **not** created at submission
time; a generate task's commit transaction creates the 10 `map` tasks for its 50-file batch —
the same "work creates work inside the completing transaction" mechanism as D3's eager
pairing. This buys an invariant worth stating plainly: **a task exists if and only if its
inputs exist, so the queue only ever contains runnable tasks.** There is no blocked/waiting
state, no DAG scheduler, no join barrier, and the claim query (D8, DM-007) never has to test
readiness. It also means a redelivered reduce or map task can never find its inputs missing.

**Why each rejection, specifically.** *At-most-once* was rejected because it converts every
crash into a correctness incident and can discard 3,125 files of completed work in one lost
partial. *2PC* was rejected because the object store cannot be a participant, so it does not
actually deliver the property it promises, while adding coordinator-blocking to a fleet of W
workers. *A membership service* was rejected because it replaces a timeout we can express in
one Postgres column with a third stateful system, still requires the per-task bookkeeping,
and its main advantage — sub-second detection — is invisible at our timescales; the
`QueueAdapter` boundary (D5) is where we would introduce it if that changed.
*Mid-task checkpointing* was rejected because K=5 already makes tasks small enough that a
checkpoint costs more than a restart.

**Failure condition.** Revisit if any of these becomes true: (a) task duration rises above
~60 s — either because K is raised well above 5 or C above 10⁶ — at which point wasted work
per crash justifies checkpointing and a per-task-type lease; (b) a task type is introduced
whose effect cannot be made idempotent (external notification, monetary side effect,
append-only export), which breaks the central assumption and forces a transactional-outbox
or dedup-log design; (c) observed duplicate-execution rate exceeds ~1% of tasks, indicating
leases are too short or heartbeats too fragile and that a real membership service is now
earning its keep; (d) `finalize`'s `count == F` assertion ever fires in a run with no
recorded `dead` task — that is a proof of a hole in the idempotency argument and takes
priority over all other work.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Crash recovery, no data loss | `kill -9` a worker mid-`map` on an F=1,000 job → job still completes and the result file matches a single-node NumPy reference to within 1e-12 per index | Chaos test in CI; reference computed in-process |
| Crash detection latency | Task returns to `pending` within 35 s of the last heartbeat (lease 30 s + reaper poll 5 s) | Timestamp delta between last `worker_heartbeat` event and the reaper's requeue event in the `events` table |
| Idempotency under forced redelivery | Force a lease expiry on an in-flight `reduce` task so two workers run it; exactly one `partials` row exists for that `task_id` and the final result is unchanged | Integration test with the reaper interval set to 0; assert `count(*) = 1` on `partials(task_id)` |
| No double-consume | Across a full F=1,000 run, every `partials` row has exactly one `consumed_by_task_id` and the set of consumed partials partitions the tree | SQL invariant check post-run: no partial consumed twice, no unconsumed partial except the final one |
| End-to-end count invariant | `finalize` observes `count == F` on 100% of successful jobs; assertion never fires without a corresponding `dead` task | Assertion in the finalize task path; audited over the full test matrix |
| Reaper is not a single point of failure | Kill the reaper for 5 minutes during a job → job completes, only makespan degrades | Chaos test; compare makespan with and without reaper downtime |
| Bounded retry cost | Duplicate-execution rate < 1% of tasks on a clean F=1,000 run | Count of tasks with `attempts > 1` ÷ total tasks |
| DB outage causes pause, not corruption | Stop Postgres for 90 s mid-job → on restart the job completes with a correct result and zero `dead` tasks | Chaos test using docker-compose pause on the Postgres container |
