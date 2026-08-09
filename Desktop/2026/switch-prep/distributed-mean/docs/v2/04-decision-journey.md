# Distributed Mean — Design by Delivery Tier

**Date:** 2026-08-10 · **Author:** Samkit Shah · **Status:** v2

Every design decision, organized by delivery tier — Scope → Bare minimum → MVP →
Edge cases → Optimizations. Each decision is stated as the question that raises it,
followed by the answer, a minimal proof, and the record that freezes it. Questions
are asked from zero knowledge; answers contain no alternatives — the full
trade-off analysis lives in the linked ITD.

---

## 1. Scope

**What must the system do?**
Accept a job `(F, C)` over an API; generate F files of C random values; compute the
index-wise mean across all F files; combine worker outputs into a single result file;
support multiple concurrent jobs; run on W system-level workers that idle until work
arrives. Bonus scope: W configurable via the API; a live UI of system state.
→ [01 §1](01-requirements-and-assumptions.md)

**What must it tolerate?**
A worker may hold at most 5 files' worth of data at a time (1 file = C float64 ≈ 8 MB
at C = 10⁶). Workers run at different speeds and must not idle while eligible work
exists. Workers crash, stall, and receive the same task twice. At the ceiling
(F ≈ 10⁵, C ≈ 10⁶) input is ≈ 800 GB — no single node may stream the whole dataset,
and no queue message may carry data.
→ [01 §2, §4](01-requirements-and-assumptions.md)

**What is out of scope?**
Authentication, multi-tenancy, quotas, cancellation (designed but not built:
`status='cancelled'` drains via the claim query's job-status filter), cross-region
operation, exactly-once delivery (replaced by idempotent effects).
→ [01 §5](01-requirements-and-assumptions.md)

**Should this be built, or should an existing compute engine be used?**
Built. The brief fixes the components (Node/Express/TS API, DB, queue, Python
workers) and the orchestration algorithm is itself the deliverable; furthermore the
design's correctness depends on one atomic transaction (consume partial results +
enqueue their combiner) that no engine exposes across its API. Absent these
constraints, an off-the-shelf data-parallel engine is the correct choice.
→ [DM-011](itds/DM-011-build-vs-offtheshelf.md)

---

## 2. Bare minimum

The smallest system that returns a *correct* mean for any valid (F, C): one API
endpoint, the queue, workers, an object store, and the completion rule. No fairness,
no fault tolerance beyond retries, no UI.

**What is the computation, mathematically?**
`output[i] = (Σ_f file_f[i]) / F`. Division by a constant commutes with summation,
and float64 vector addition is associative and commutative — so the problem is a
fold over a commutative monoid, which admits order-free, coordinator-free
aggregation. Every decision below inherits from this fact.
→ [HLD §1](02-hld.md)

**What should workers exchange with each other?**
Sum-vectors paired with a count of files covered: `(Σ, n)`. Proof of necessity:
averaging averages is only correct for equal group sizes — F = 12 splits 5+5+2, and
with ten files of 0.0 and two of 1.0 the true mean is 0.1667 while the average of
group-averages is 0.3333. Carrying `(Σ, n)` makes the weighting structural; division
by F happens exactly once, at the end.
→ [DM-001](itds/DM-001-aggregation-topology.md), [DM-010](itds/DM-010-numerical-correctness.md)

**How is the job divided, given a worker holds at most five files?**
Into tasks of ≤ 5 files each (`map`), producing ⌈F/5⌉ partial results. A partial is
C float64s — the same shape as a file — so the 5-file limit binds combination steps
identically: combining partials requires its own tasks (`reduce`, fan-in ≤ 5),
recursively, giving ⌈log₅⌈F/5⌉⌉ levels (7 at F = 10⁵). A flat combine is impossible
by the constraint itself.
→ [DM-001](itds/DM-001-aggregation-topology.md)

**When do combination tasks get created?**
At the moment enough inputs exist: whenever a job has ≥ 5 unconsumed partials, the
transaction committing the newest one atomically claims five and enqueues a `reduce`.
The combination tree is therefore never planned in advance — it emerges from
completion order, so no task ever waits on a specific sibling. The pairing step is
serialised per job with an advisory lock; otherwise two simultaneous committers can
each see an incomplete picture and both decline, leaving the job permanently stalled
(reachable at F = 7 with two workers).
→ [DM-002](itds/DM-002-work-distribution-stragglers.md), [LLD §4](03-lld.md)

**How do tasks reach workers?**
Workers pull from a shared queue when free; nothing is ever assigned. The queue is a
Postgres table claimed with `FOR UPDATE SKIP LOCKED`. Proof of fit: the pairing step
above must atomically {mark partials consumed + insert their reduce task}; with an
external broker either write order fails (commit-then-send strands the partials;
send-then-commit double-counts sums), while in Postgres it is one transaction. Load
is ~27k tasks per maximal job at seconds each — well inside a single table's range.
→ [DM-004](itds/DM-004-queue-technology.md), claim SQL in [LLD §3](03-lld.md)

**Where do the bytes live?**
An S3-API object store (MinIO locally, S3 on AWS); the queue and database carry URIs
only. An 8 MB partial exceeds queue-message limits by ~32×. Inputs are CSV; partials
are raw little-endian float64 (8 MB vs ~20 MB, zero parse cost in both languages).
→ [DM-005](itds/DM-005-data-placement-and-format.md)

**How does the system know a job is finished?**
By proof: `map` and `reduce` preserve the total count of covered files, and
consumption is exactly-once, so a job's unconsumed partials always partition its F
files — a lone unconsumed partial with `count = F` therefore *is* the completed sum
(cannot occur early, cannot be missed). Paired with one liveness check (no
pending/claimed tasks for the job), evaluated inside the same committing
transaction. A `finalize` task divides by F and writes the result.
→ [DM-003](itds/DM-003-job-completion-detection.md)

**Who creates the input files?**
Distributed `generate` tasks (~50 files each, per-file deterministic seeds), riding
the same queue — generating 800 GB on the API's submit path would serialise the job
before it starts. Each generate task spawns its batch's map tasks on completion.
→ [LLD §2](03-lld.md)

---

## 3. MVP

Adds to the bare minimum everything required for real operation: concurrent users,
crashing workers, result delivery, and the two bonus requirements.

**What happens when several jobs run at once?**
The claim query orders candidates by (tasks in flight for that job ASC, task
priority, age) — the least-served job always goes first, yielding round-robin
without a scheduler. A 4-task job entering behind a 27,000-task job completes in
roughly its own work time instead of hours; the large job loses ~0.01% of its
worker-seconds. Priority runs `finalize > reduce > map > generate` because reduce
depth is the critical path and map width is surplus parallelism.
→ [DM-007](itds/DM-007-multi-job-fairness.md)

**What happens when a worker dies mid-task?**
Every claim carries a 30 s lease, extended by a 10 s heartbeat; a reaper (5 s sweep)
returns expired tasks to the queue — crash detection ≤ 35 s. After three attempts a
task is dead and its job fails with a recorded cause.
→ [DM-006](itds/DM-006-state-model-failure-handling.md)

**How can a task safely run twice?**
All effects are idempotent: output objects have deterministic names derived from the
task (a retry overwrites itself byte-identically — generation is seeded per file, so
even inputs regenerate exactly); the partial-metadata insert is unique per producing
task; commits and heartbeats are fenced by a per-claim token plus task status, and
the reaper rotates the token on requeue. At-least-once delivery plus idempotent
effects is outcome-equivalent to exactly-once.
→ [DM-006](itds/DM-006-state-model-failure-handling.md)

**How does the user receive the result?**
`GET /jobs/:id/result` returns `302` to a 15-minute pre-signed URL, keeping the API
off the data plane (a C = 10⁶ result is ~20 MB); `?inline=1` proxies the stream.
Completion is discovered via the `job.completed` event or by polling. Submission is
idempotent via an `Idempotency-Key` header; jobs exceeding `MAX_JOB_BYTES` or the
active-job cap are rejected at the door (`413`/`429`).
→ [DM-005](itds/DM-005-data-placement-and-format.md), [LLD §6](03-lld.md)

**How is the number of workers controlled through the API?** *(bonus)*
The API writes `desired_workers`; a supervisor loop converges actual to desired —
docker compose scale locally, `ecs.updateService(desiredCount)` on AWS. Scale-down
drains gracefully (finish task, commit, exit) with the lease as backstop, so
correctness never depends on the drain. A worker is one process: a fault costs one
lease, and W remains a single knob.
→ [DM-008](itds/DM-008-worker-pool-w-configurability.md)

**How does an operator watch the system?** *(bonus)*
An append-only `events` table streamed over SSE (auto-reconnect with
`Last-Event-ID`; a BIGSERIAL id makes resume a one-line predicate), with task-level
noise folded into a 1 Hz snapshot. Per-job progress is file coverage,
`(mapped + consumed) / (F + R_est)` — monotone because it is derived from
idempotently-keyed state rows, clamped at 99% so only `finalize` reports 100%. Two
stall gauges (oldest pending / oldest claimed task age) are the alerting signals.
→ [DM-009](itds/DM-009-observability-ui.md)

**How does it deploy?**
Locally: docker-compose (API, Postgres 16, MinIO, W workers, supervisor, static UI).
AWS: the same containers on ECS Fargate + RDS Multi-AZ + S3 behind an ALB — a
configuration change, not a rewrite.
→ [HLD §6](02-hld.md), [LLD §9](03-lld.md)

---

## 4. Edge cases

| Case | Behaviour | Ref |
|---|---|---|
| F ≤ 5 | One map task produces a partial with count = F directly; no reduce ever runs; same machinery, no special path. | DM-001 |
| F not divisible by 5 | The remainder rides as a smaller map task; `(Σ, n)` weighting makes unequal groups correct by construction. | DM-001 |
| Job's last partials arrive with < 5 available and nothing else running | Drain mode: reduce at fan-in 2–4 instead of waiting for a fifth that will never come; costs ≤ ~7 extra reduces (< 0.15%). | DM-002 |
| Two workers commit a job's last two partials simultaneously | The per-job advisory lock serialises pairing; the second committer sees the first's partial and acts. | DM-002, LLD §4 |
| Worker crashes holding a task | Lease expires ≤ 35 s; task requeued; deterministic output keys make the retry harmless. | DM-006 |
| Worker stalls but its heartbeat thread stays alive | Absolute `TASK_DEADLINE` (300 s) stamped at claim; heartbeats cannot extend past it; reaper reclaims regardless. | DM-006 |
| Zombie worker commits after its lease was reaped | Fenced commit (`lease_token` + `status='claimed'`) matches zero rows; the write is discarded; its earlier PUT is byte-identical to the retry's. | DM-006 |
| Same reduce task delivered twice | Its input set was fixed at creation (partials already marked consumed), so both executions read the same inputs and write the same key. | DM-006 |
| Duplicate `POST /jobs` | `Idempotency-Key` returns the original job; without the header a distinct job is created by design. | LLD §6 |
| Oversized or flooding submissions | `413` above `MAX_JOB_BYTES`; `429` + `Retry-After` above `MAX_ACTIVE_JOBS`. | LLD §6 |
| Result requested before completion | `409`; completion is announced via `job.completed` event. | LLD §6 |
| Queue momentarily empty but job unfinished | Never read as completion — the completion rule is the count = F proof, not queue depth. | DM-003 |
| Reaper or supervisor down | Leases expire late / W drifts: degraded, never incorrect; a backstop sweep exists purely as a bug detector. | DM-006, DM-003 |
| Database down | System pauses; workers back off; no state is lost or corrupted. | DM-006 |
| Object store errors | Bounded client timeouts (5 s connect / 30 s read) fail the task into the normal retry path. | DM-006 |
| Progress bar under dynamic task creation | Coverage-based numerator over a fixed denominator estimate; monotone by construction, never reports 100% before finalize. | DM-009 |

---

## 5. Optimizations

### 5.1 In the design

**Full fan-in during steady state.**
- *Mechanism:* reduce at fan-in 5 whenever 5 partials exist; total reduce bytes scale
  as k/(k−1), minimized at the largest legal k.
- *Effect:* ~200 GB reduce reads at k=5 vs ~320 GB at k=2; 4× fewer tasks; half the depth.
- → [DM-002](itds/DM-002-work-distribution-stragglers.md)

**Map/reduce overlap.**
- *Mechanism:* eager pairing lets fast workers combine finished partials while slow
  workers are still mapping; no phase barrier exists anywhere.
- *Effect:* a straggler delays only its own ~8 MB of work, never a phase or a branch.
- → [DM-002](itds/DM-002-work-distribution-stragglers.md)

**Task-type priority in the claim order.**
- *Mechanism:* `finalize > reduce > map > generate` in the claim query's ORDER BY.
- *Effect:* shortens the critical path (reduce depth), frees partial storage early,
  and unblocks waiting users first.
- → [DM-007](itds/DM-007-multi-job-fairness.md)

**Binary intermediate format.**
- *Mechanism:* raw float64 partials instead of text.
- *Effect:* 2.5× smaller, zero parse cost on both the TypeScript and Python sides.
- → [DM-005](itds/DM-005-data-placement-and-format.md)

**Pairwise-structured summation.**
- *Mechanism:* the reduction tree is pairwise summation by construction.
- *Effect:* error O(log₅F·ε) ≈ 9×10⁻¹⁶ at F = 10⁵ — accuracy-neutral against the
  standard single-node baseline; ~10⁴× tighter than a naive serial accumulator.
- → [DM-010](itds/DM-010-numerical-correctness.md)

### 5.2 Deferred, with triggers

**Speculative re-execution of tail tasks.**
- *Trigger:* p99 job completion > 1.5× the aggregate-throughput projection, attributed
  to a slow-but-alive worker on the critical path.
- *Mechanism:* duplicate the projected-last tasks; first commit wins (idempotency
  already makes duplicates safe). Scope first to the top reduce levels where
  duplicate I/O is cheapest.
- *Cost:* duplicate reads (~40 MB per speculated leaf).
- → [DM-002](itds/DM-002-work-distribution-stragglers.md)

**Queue wake-up without polling.**
- *Trigger:* measured claim latency from the 500 ms idle poll becomes material.
- *Mechanism:* `LISTEN/NOTIFY` on task insert; drop-in.
- → [DM-004](itds/DM-004-queue-technology.md)

**Broker migration.**
- *Trigger:* sustained > 5k tasks/s, cross-region consumers, or multi-service fan-out.
- *Mechanism:* SQS behind the existing `QueueAdapter`, with a transactional outbox
  replacing direct enqueue.
- *Cost:* an outbox to build and a broker to operate; the atomic pairing transaction
  must be re-derived.
- → [DM-004](itds/DM-004-queue-technology.md)

**Connection scaling.**
- *Trigger:* W approaching the hundreds.
- *Mechanism:* PgBouncer in transaction mode; workers already hold one connection each.
- → [DM-004](itds/DM-004-queue-technology.md)

**In-worker pre-combining.**
- *Trigger:* intermediate I/O measured above ~40% of job wall-clock.
- *Mechanism:* a worker finishing multiple maps combines locally before writing,
  collapsing a tree level (level-0 traffic 160 GB → ~32 GB).
- → [DM-001](itds/DM-001-aggregation-topology.md)

**Column-dimension sharding.**
- *Trigger:* C grows to where one vector (~C × 8 B) exceeds a worker's memory budget
  (roughly C > 10⁸).
- *Mechanism:* stream column blocks within a task; topology unchanged.
- → [DM-001](itds/DM-001-aggregation-topology.md)

**Deterministic reduction tree.**
- *Trigger:* bit-identical outputs across runs become a requirement.
- *Mechanism:* canonical pairing order by partial id, drain mode off.
- *Cost:* reintroduces waiting on specific siblings; tail latency rises.
- → [DM-010](itds/DM-010-numerical-correctness.md)

**Compensated summation.**
- *Trigger:* value bounds widen enough that O(log F·ε) error is material.
- *Mechanism:* Kahan/Neumaier accumulators inside tasks.
- *Cost:* doubles partial size and level-0 traffic.
- → [DM-010](itds/DM-010-numerical-correctness.md)

**Queue-depth autoscaling of W.**
- *Trigger:* the user-set-W requirement is relaxed in favour of cost/latency targets.
- *Mechanism:* ECS target tracking (or KEDA) on queue depth and oldest-pending age.
- → [DM-008](itds/DM-008-worker-pool-w-configurability.md)

**Weighted fairness.**
- *Trigger:* tenants or priority classes appear.
- *Mechanism:* the claim ORDER BY generalises to weighted fair queuing.
- → [DM-007](itds/DM-007-multi-job-fairness.md)

**Storage lifecycle.**
- *Trigger:* always-on operation.
- *Mechanism:* delete `inputs/` and `partials/` on job completion (config-gated);
  archive finished task rows nightly to keep the queue table small.
- → [DM-004](itds/DM-004-queue-technology.md), [DM-005](itds/DM-005-data-placement-and-format.md)

---

## Traceability to the brief

| Brief's criterion | Tier | Frozen in |
|---|---|---|
| F > 5: no 1:1 job↔queue item | Bare minimum | DM-001/002, LLD §2 |
| Efficiency of task distribution | Bare minimum + Optimizations 5.1 | DM-002, DM-007 |
| Deciding a job is finished | Bare minimum | DM-003 |
| Multiple jobs concurrently | MVP | DM-007 |
| Minimal idling, heterogeneous speeds | Bare minimum + Optimizations 5.1 | DM-002 |
| Combine worker outputs into final file | Bare minimum | DM-001, DM-010 |
| **Bonus:** W via API | MVP | DM-008 |
| **Bonus:** live UI | MVP | DM-009 |
