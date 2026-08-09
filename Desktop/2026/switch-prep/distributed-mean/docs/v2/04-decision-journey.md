# Distributed Mean — Decision Index

**Date:** 2026-08-10 · **Author:** Samkit Shah · **Status:** v2

Every design decision as a question → the chosen answer with one line of reasoning →
the alternatives, one line each. Full arguments, proofs, and trade-off analysis live
in the linked ITDs. Tiers: **Scope** (what and why) → **Bare minimum** (the smallest
*correct* system) → **MVP** (the smallest *operable* system) → **Optimizations** →
**Edge cases**.

---

## 1. Scope

**What must the system do?** Accept an `inputUris[]` of F **pre-existing** weight files of
C float64 values over an API (the federated-learning setting: the vectors already sit on
the nodes that trained them); compute the index-wise mean; combine worker outputs into one
result file; run multiple jobs concurrently on W pull-based workers. Bonus: W configurable
via API; live UI. → [01 §1](01-requirements-and-assumptions.md)

**What must it tolerate?** K = 5 files per worker (1 file = 8 MB at C = 10⁶);
heterogeneous worker speeds with minimal idling; crashes, stalls, duplicate
deliveries; inputs on nodes we do not control, reached by user-supplied URIs;
≈ 800 GB read at the ceiling — no single-node streaming, no data in
queue messages. → [01 §2, §4](01-requirements-and-assumptions.md)

**What is out of scope?** Input generation (inputs pre-exist), weighted aggregation
(the mean is unweighted; weighted FedAvg is a documented evolution, §4), auth,
multi-tenancy, quotas, cancellation (designed, not built), cross-region, exactly-once
delivery (replaced by idempotent effects).
→ [01 §5](01-requirements-and-assumptions.md)

**Build, or adopt an existing engine?**
→ **Build on primitives** — the brief fixes the components and the orchestration
algorithm is the deliverable; the correctness spine (consume partials + enqueue
combiner, atomically) fits no engine's transaction boundary. [DM-011](itds/DM-011-build-vs-offtheshelf.md)
- *Spark/Dask*: computes this in six lines but erases the deliverable and assumes homogeneous, co-scheduled executors.
- *Temporal/Step Functions*: ~25k activities per job fights its history model; the consumption invariant stays outside its transactions.
- *Celery/RQ/Ray*: counter-based fan-in plus a broker↔DB dual-write; TS producer is second-class.

---

## 2. Bare minimum — the smallest correct system

Returns an exact mean for any valid (F, C), end to end. Acceptance: correctness only.

**What is the computation, structurally?**
→ **A fold over a commutative monoid** — sums are associative and commutative, so
aggregation can be order-free and coordinator-free; divide by F once at the end.
[HLD §1](02-hld.md) *(no alternatives — this is arithmetic)*

**What do workers exchange?**
→ **(sum-vector, count) pairs** — makes any grouping correct by construction; at
F = 12 (groups 5+5+2) averaging averages returns 0.333 for a true 0.167. [DM-001](itds/DM-001-aggregation-topology.md)
- *Means*: silently wrong for unequal groups, and unequal groups are the normal case.
- *Raw values*: data volume never shrinks; combiners would re-read everything.

**How is the job divided under the 5-file limit?**
→ **Map tasks of ≤ 5 files, then recursive ≤ 5-fan-in reduce tasks** — a partial is
file-shaped, so the limit binds combiners too; depth ⌈log₅⌈F/5⌉⌉ = 7 at F = 10⁵. [DM-001](itds/DM-001-aggregation-topology.md)
- *Flat combine*: illegal — 20,000 inputs against a fan-in of 5.
- *Sharding the C dimension*: wrong axis — the constraint counts files, not vector width.

**When are combine tasks created?**
→ **Eagerly, whenever ≥ 5 partials exist, inside the committing transaction under a
per-job advisory lock** — no task ever waits on a named sibling, and concurrent
committers cannot both undercount and both decline. [DM-002](itds/DM-002-work-distribution-stragglers.md)
- *Pre-planned tree*: one slow child stalls its branch despite ready partials elsewhere.
- *Map-all-then-reduce barrier*: the slowest of 20,000 maps gates every combiner.
- *Central streaming accumulator*: feasible on memory (8 MB) but 160 GB through one NIC is a serial floor.

**How do tasks reach workers, and on what queue?**
→ **Workers pull from a Postgres `FOR UPDATE SKIP LOCKED` table** — pairing must
atomically {consume partials + insert their reduce}, and only the DB-as-queue makes
that one transaction; load (~25k tasks/job, seconds each) is far inside its range. [DM-004](itds/DM-004-queue-technology.md)
- *SQS*: enqueue + DB state is a dual-write; either order strands work or double-counts sums; the outbox fix rebuilds a DB queue anyway.
- *RabbitMQ*: same dual-write, plus a broker to operate.
- *Redis*: same dual-write with weaker delivery semantics.
- *Push assignment*: speed estimates are always stale; mis-assignments become idle time.

**How is idle time kept low across heterogeneous speeds?**
→ **The pull model itself, plus map/reduce overlap** — a 3× faster worker claims 3×
as often; a slow worker's blast radius is one task regardless of F. [DM-002](itds/DM-002-work-distribution-stragglers.md)
- *Speed-tracking scheduler*: adds an estimator whose every error is idle time.
- *Speculative re-execution*: duplicate I/O for a tail the leases already bound — deferred (§4).

**Where do the bytes live?**
→ **S3-API object store throughout (MinIO local / S3 on AWS); queue and DB carry URIs.
Inputs stay where the nodes put them — read-only, allow-listed, in CSV or raw `.f64`; our
bucket holds raw float64 partials and the CSV result** — an 8 MB partial exceeds message
limits ~32×; binary is 2.5× smaller than CSV and eliminates parsing in both languages.
[DM-005](itds/DM-005-data-placement-and-format.md)
- *API-local filesystem*: single-node with no fleet story — and it cannot reach inputs held on other nodes at all.
- *NFS/EFS*: multi-node but weak consistency/throughput for this pattern.
- *In the DB or in messages*: puts the data plane on the control plane; dies at 8 MB × 25k objects.
- *Copy inputs into our bucket first*: 800 GB of pure duplication before any arithmetic, for no property we lack.

**How does the system know a job is finished?**
→ **A lone unconsumed partial with count = F, plus no tasks in flight** — counts are
conserved and consumption is exactly-once, so unconsumed partials always partition
the F files: the condition is a proof, evaluated in the committing transaction. [DM-003](itds/DM-003-job-completion-detection.md)
- *Task counter*: the task count is dynamic and redelivery corrupts decrements.
- *Polling coordinator*: adds latency and a component to notice what the transaction already knows.
- *Queue-empty*: racy, and meaningless with concurrent jobs.

**How does work reach the queue for inputs that already exist?**
→ **T1 creates all ⌈F/5⌉ `map` tasks in the submit transaction**, chunking the submitted
`inputUris[]` by K=5 in list order — the partition is a pure function of the request, so
nothing needs to be observed first, and no task ever spawns another. [LLD §4 T1](03-lld.md)
- *Spawn map tasks dynamically*: would need a natural key to dedupe retried spawns; with the URIs known at submit there is nothing to gain from paying for it.
- *One queue item per input file*: 100k tasks that each violate nothing but waste 5× the bookkeeping and forfeit the K=5 batching.

---

## 3. MVP — the smallest operable system

Bare minimum + survives real use: concurrent users, crashing workers, delivery,
observability, both bonuses. Acceptance: operability.

**Several jobs at once — who gets the workers?**
→ **Least-served job first, via the claim query's ORDER BY (in-flight ASC, priority,
age)** — a 2-task job behind a 25k-task job finishes in its own work time; the big
job loses ~0.01%. [DM-007](itds/DM-007-multi-job-fairness.md)
- *FIFO*: hours of convoy for seconds of work; more workers never reorder it.
- *Per-job queues*: dynamic queue management for what one ORDER BY does.
- *Weighted fair queuing*: needs tenant semantics that don't exist — deferred (§4).

**What happens when a worker dies mid-task?**
→ **30 s lease + 10 s heartbeat + 5 s reaper, under a flat absolute task deadline of
300 s (the heaviest type, `map`, moves ~108 MB in ~2.2 s — ~135× headroom)** —
detection ≤ 35 s, task requeued, three attempts then the job fails loudly (`finalize`
gets ten, because failing it would discard a finished computation).
[DM-006](itds/DM-006-state-model-failure-handling.md)
- *At-most-once*: silently loses work.
- *2PC/exactly-once*: unattainable across queue + object store; costs latency chasing it.
- *External membership service (ZK/etcd)*: a second stateful system for what a column does.

**How can the same task safely run twice?**
→ **Idempotent effects: deterministic output keys, token+status-fenced commits and
heartbeats, unique partial-per-task inserts** — at-least-once plus idempotency is
outcome-equivalent to exactly-once. [DM-006](itds/DM-006-state-model-failure-handling.md)
- *Execution-time dedupe*: racy; prevention at the effect layer is unconditional.
- *Storage-layer fencing*: unnecessary once the write itself is idempotent.

**How does the user get the result?**
→ **`302` to a 15-minute pre-signed URL (`?inline=1` to proxy)** — keeps the API off
the data plane; completion announced by event or poll; submissions idempotent by
header; oversized/flooding jobs rejected at the door. [DM-005](itds/DM-005-data-placement-and-format.md), [LLD §6](03-lld.md)
- *API streams the file*: puts a 20 MB body per download through the control plane.
- *Webhooks*: no authenticated callee exists to sign for.

**How is W controlled through the API?** *(bonus)*
→ **API writes `desired_workers`; a supervisor reconciles actual → desired** —
compose scale locally, `ecs.updateService` on AWS; drain is graceful with the lease
as backstop; one process per worker keeps a fault's cost to one lease. [DM-008](itds/DM-008-worker-pool-w-configurability.md)
- *Fixed W in compose*: forfeits the bonus.
- *Workers self-managing their population*: bootstrap and scale-down races.
- *Queue-depth autoscaling*: the requirement is user-set W — deferred (§4).

**How does an operator watch the system?** *(bonus)*
→ **Append-only events + SSE, task noise folded into a 1 Hz snapshot; progress =
file coverage, clamped at 99% until finalize** — monotone by construction where
done/total would move backwards as reduce tasks appear. [DM-009](itds/DM-009-observability-ui.md)
- *Polling only*: N-second latency and chatter — kept as fallback.
- *WebSockets*: bidirectional machinery for a one-way flow; no built-in resume.
- *Prometheus/Grafana*: right at production scale, heavyweight here — deferred (§4).

**How does it deploy?**
→ **docker-compose locally; the same containers on ECS Fargate + RDS + S3 behind an
ALB** — a configuration change, not a rewrite. [HLD §6](02-hld.md) *(no contested alternatives)*

---

## 4. Optimizations

### In the design

- **Fan-in 5 in steady state** — reduce bytes scale as k/(k−1): ~200 GB at k=5 vs ~320 GB at k=2, 4× fewer tasks, half the depth. [DM-002](itds/DM-002-work-distribution-stragglers.md)
- **Drain-mode fan-in 2–4 in the tail** — removes an unbounded stall for ≤ ~7 extra reduces (< 0.15%). [DM-002](itds/DM-002-work-distribution-stragglers.md)
- **Map/reduce overlap** — no phase barrier anywhere; a straggler delays only its own 8 MB. [DM-002](itds/DM-002-work-distribution-stragglers.md)
- **Claim priority `finalize > reduce > map`** — shortens the critical path and frees storage first. [DM-007](itds/DM-007-multi-job-fairness.md)
- **Raw float64 partials** — 2.5× smaller than CSV, zero parse cost both sides. [DM-005](itds/DM-005-data-placement-and-format.md)
- **Pairwise-structured summation** — error O(log₅F·ε) ≈ 9×10⁻¹⁶ at F = 10⁵; accuracy-neutral vs the standard single-node baseline. [DM-010](itds/DM-010-numerical-correctness.md)

### Deferred, with triggers

- **Speculative tail re-execution** — if p99 completion > 1.5× throughput projection: duplicate the projected-last tasks, first commit wins (idempotency makes it safe). [DM-002](itds/DM-002-work-distribution-stragglers.md)
- **`LISTEN/NOTIFY` wake-up** — if the 500 ms idle poll's claim latency matters: drop-in. [DM-004](itds/DM-004-queue-technology.md)
- **SQS + transactional outbox** — at sustained > 5k tasks/s, cross-region consumers, or multi-service fan-out; behind the existing `QueueAdapter`. [DM-004](itds/DM-004-queue-technology.md)
- **PgBouncer** — as W approaches the hundreds. [DM-004](itds/DM-004-queue-technology.md)
- **In-worker pre-combining** — if intermediate I/O > ~40% of wall-clock: combine locally before writing, level-0 traffic 160 → ~32 GB. [DM-001](itds/DM-001-aggregation-topology.md)
- **Column-block streaming within tasks** — if C grows past ~10⁸ (vector > worker RAM); topology unchanged. [DM-001](itds/DM-001-aggregation-topology.md)
- **Deterministic tree** — if bit-identical outputs become required: canonical pairing order, drain off; tail latency rises. [DM-010](itds/DM-010-numerical-correctness.md)
- **Kahan/compensated summation** — if incoming weight magnitudes widen; doubles partial size and level-0 traffic. [DM-010](itds/DM-010-numerical-correctness.md)
- **Data locality in claim order** — if measured cross-node input-read bandwidth dominates map time: prefer `map` tasks whose input node is co-located with the claiming worker, falling back to any eligible task so the queue stays work-conserving. [DM-002](itds/DM-002-work-distribution-stragglers.md), [DM-005](itds/DM-005-data-placement-and-format.md)
- **Weighted FedAvg** — if aggregation must weight clients by sample count: partials carry `(Σ wᵢ·xᵢ, Σ wᵢ)` instead of `(Σ xᵢ, n)` and `finalize` divides Σwx by Σw. Same monoid, same tree, payload +8 bytes. [DM-001](itds/DM-001-aggregation-topology.md), [DM-010](itds/DM-010-numerical-correctness.md)
- **Queue-depth autoscaling of W** — if user-set W is relaxed for cost/latency targets. [DM-008](itds/DM-008-worker-pool-w-configurability.md)
- **Weighted fairness** — when tenants or priority classes appear; the ORDER BY generalises. [DM-007](itds/DM-007-multi-job-fairness.md)
- **Prometheus/Grafana metrics stack** — at production scale, replacing events-table diagnostics with proper SLI/SLO material. [DM-009](itds/DM-009-observability-ui.md)
- **Storage lifecycle** — always-on operation: GC intermediates on completion, archive finished task rows nightly. [DM-004](itds/DM-004-queue-technology.md), [DM-005](itds/DM-005-data-placement-and-format.md)

---

## 5. Edge cases

| Case | Behaviour | Ref |
|---|---|---|
| F ≤ 5 | One map yields count = F directly; no reduce runs; no special path. | DM-001 |
| F not divisible by 5 | Remainder rides as a smaller map; (Σ, n) makes unequal groups correct. | DM-001 |
| < 5 partials left, nothing else running | Drain mode reduces at fan-in 2–4 instead of waiting forever. | DM-002 |
| Last two partials commit simultaneously — or the reaper requeues concurrently | Per-job advisory lock serialises pairing; the second sees the first. T3 also pairs, under the same job lock, for every job whose task it requeues — so a reaped task's missing commit is not a missing trigger. | DM-002, DM-003, LLD §4 |
| Worker crashes holding a task | Lease expires ≤ 35 s; requeue; deterministic keys make the retry harmless. | DM-006 |
| Worker wedged, heartbeat alive | Absolute 300 s task deadline, stamped at claim time; heartbeats cannot extend past it. | DM-006 |
| Executor raises inside a task | T4: the worker requeues its own task, fenced by its lease token; requeue *is* the retry, so there is no transient `failed` state. | DM-006, LLD §4 |
| `finalize` exhausts its attempts | `finalize` gets 10 attempts, and a job holding an unconsumed `count = F` partial is never flipped to `failed` — the reaper emits `job.needs_finalize` instead. | DM-006, LLD §4 |
| Zombie commits after reaping | Fenced commit matches zero rows; earlier PUT is byte-identical to the retry's. | DM-006 |
| Same reduce delivered twice | Input set fixed at creation; both runs read the same inputs, write the same key. | DM-006 |
| Input URI unreachable, missing, or of the wrong length | The `map` task fails past the blob client's bounded retries (or on the C check at read), T4 requeues, three attempts, then `dead` → job `failed` with the offending URI in `last_error`. A length mismatch is permanent and still costs its three attempts — retrying is cheap, a permanence branch is not. | DM-006, LLD §5, §6 |
| Input URI outside the allow-list, or repeated in the list | Rejected `422` at submit — no job row, no tasks. A repeated URI would double-weight that vector. | LLD §6, HLD §9 |
| Duplicate `POST /jobs` | `Idempotency-Key` returns the original job; absent it, distinct by design. | LLD §6 |
| Oversized / flooding submissions | `413` over `MAX_JOB_BYTES`; `429` + `Retry-After` over the active-job cap. | LLD §6 |
| Result requested early | `409`; completion announced via `job.completed`. | LLD §6 |
| Queue empty, job unfinished | Never read as done — completion is the count = F proof, not queue depth. | DM-003 |
| Reaper or supervisor down | Late lease expiry / W drift: degraded, never incorrect. | DM-006 |
| Database down | System pauses; no state lost or corrupted. | DM-006 |
| Object store errors | Bounded client timeouts fail the task into the normal retry path — which is T4's requeue, the same path a crash takes. | DM-006 |
| Progress under dynamic task creation | Coverage-based and monotone; only finalize reports 100%. | DM-009 |

---

## Traceability to the brief

| Brief's criterion | Tier | Frozen in |
|---|---|---|
| F > 5: no 1:1 job↔queue item | Bare minimum | DM-001/002, LLD §2 |
| Efficiency of task distribution | Bare minimum + Optimizations | DM-002, DM-007 |
| Deciding a job is finished | Bare minimum | DM-003 |
| Multiple jobs concurrently | MVP | DM-007 |
| Minimal idling, heterogeneous speeds | Bare minimum + Optimizations | DM-002 |
| Combine worker outputs into final file | Bare minimum | DM-001, DM-010 |
| **Bonus:** W via API | MVP | DM-008 |
| **Bonus:** live UI | MVP | DM-009 |

## The design in one breath

> Element-wise mean is a monoid fold, so workers exchange (sum, count) partials that
> any worker can merge in any order; the 5-file RAM limit applies to partials too,
> forcing a 5-ary reduction tree that is never pre-built — reduces are enqueued
> eagerly as partials appear, so fast workers reduce while slow ones map. Completion
> is the conservation proof that a lone partial with count = F is the answer. The
> queue is Postgres SKIP LOCKED because consume-and-enqueue must be one transaction;
> retries are harmless because every output key is deterministic; fairness is an
> ORDER BY; W is a supervisor reconciling a number the API writes; and the UI streams
> SSE with a progress bar that cannot move backwards.
