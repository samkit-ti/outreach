# Distributed Mean — The Decision Journey

**Date:** 2026-08-10 · **Author:** Samkit Shah · **Status:** v2

**What this is:** the design, derived as a sequence of questions — the questions anyone
would have to ask, in the order they arise, each answered with the shortest honest
proof and frozen in a decision record. Read top to bottom and you re-derive the whole
system; each question only depends on the answers above it. Inline refs point to the
full arguments: [DM-0XX](itds/) for decision records, [HLD](02-hld.md) / [LLD](03-lld.md)
for the resulting structure. The brief's critical aspects and both bonus items are
mapped at the end.

---

## Q0 — What am I actually being asked to compute?

Strip the wrapper (API, queue, workers) and the job is `output[i] = (Σ_f file_f[i]) / F`.
Division by a constant commutes with everything, so the hard part is a **big sum** —
and summation of float64 vectors is **associative and commutative** (a commutative
monoid, up to rounding). Problems built on a monoid admit *tree-shaped, order-free,
coordinator-free* aggregation. That single algebraic observation seeds every decision
below.

**Frozen:** treat the job as a distributed fold; design for the monoid, not for
"files". → [HLD §1](02-hld.md), [01 §1–2](01-requirements-and-assumptions.md)

## Q1 — Why build this at all, when Spark computes it in six lines?

Asked before designing anything, because if the answer is "adopt an engine" the rest
is moot. Three reasons to build: the brief fixes the components (Node/Express/TS API,
DB, queue, Python workers) and the orchestration algorithm is itself the deliverable;
Spark's driver/executor model assumes homogeneous, co-scheduled executors — an
assumption the brief explicitly withdraws; and the design's eventual correctness spine
(consume partials + enqueue their reducer, atomically) must live inside one
transaction, which no engine exposes across its API. Absent these constraints, Spark
`treeAggregate` is the right answer — the rejection is context-bound.

**Frozen:** build on primitives. → [DM-011](itds/DM-011-build-vs-offtheshelf.md)

## Q2 — How big is this, really?

F < 100k files × C < 1M values = up to 10¹¹ float64 ≈ **800 GB** of input. One file —
and one partial result — is C float64 ≈ **8 MB**. Two immovable consequences: no
single node may stream the whole dataset (a serial floor no worker count can lower),
and the queue can never carry data (8 MB ≫ any sane message size; SQS caps at 256 KB).
So: **control plane moves references, data plane moves bytes.**

**Frozen:** control/data-plane split; object store for bytes, DB rows for state.
→ [01 §4](01-requirements-and-assumptions.md), [DM-005](itds/DM-005-data-placement-and-format.md)

## Q3 — What should workers pass around — means, or something else?

Means are a trap. Mean-of-means is only correct for equal group sizes: with F = 12
split 5+5+2, ten files of 0.0 and two of 1.0 give a true mean of 2/12 = 0.1667, but
mean-of-means says (0+0+1)/3 = 0.3333 — silently 2× off. F is user-chosen, so unequal
groups are the normal case. Carrying **(sum-vector, count)** makes the weighting
structural: any grouping, any order, same answer. Divide by F exactly once, at the end.

**Frozen:** partials are `(Σ, n)`; a single division in `finalize`.
→ [DM-001](itds/DM-001-aggregation-topology.md), [DM-010](itds/DM-010-numerical-correctness.md)

## Q4 — Twenty thousand partial results will exist. Who combines them?

Here the constraint bites twice: a partial is C float64s = 8 MB — *exactly
file-shaped* — so the "≤5 files at a time" RAM limit binds reducers the same way it
binds mappers. Combining ⌈F/5⌉ = 20,000 partials therefore requires a **5-ary tree**:
20k → 4k → 800 → 160 → 32 → 7 → 2 → 1 — about 5,000 reduce tasks over ~7 levels, with
depth growing as log₅F. There is no legal flat design; recursion is forced, not chosen.

**Frozen:** recursive 5-ary reduction. → [DM-001](itds/DM-001-aggregation-topology.md)

## Q5 — Couldn't one node just stream `acc += partial`? Or: why not map-all-then-reduce?

The two tempting shortcuts, killed for the right reasons:
- **Central accumulator:** memory is *not* the objection — the accumulator is O(C) =
  8 MB. Bandwidth is: all 160 GB of level-0 partials must cross one NIC (~21 min at
  1 Gbps), a serial floor that adding workers cannot shrink, and the API becomes
  stateful (breaking restarts and multi-instance deployment). It also defeats the
  purpose of the 5-file constraint while honoring its letter.
- **Two-phase barrier:** the slowest of 20,000 maps gates every reduce — with
  heterogeneous worker speeds, the barrier makes the slowest worker the job's clock.
  And it buys nothing: phase 2 still needs the same 5-ary tree.

**Frozen:** neither; the tree runs *through the queue* as ordinary tasks.
→ [DM-001](itds/DM-001-aggregation-topology.md)

## Q6 — Should the reduction tree be planned up front, or discovered as results arrive?

A planned tree wires each reduce to five *named* children — one slow child stalls the
branch even with fifty other partials sitting ready, which is the barrier problem
reborn at every internal node. But Q0 says any partials are combinable. So the tree is
**never pre-built**: whenever ≥5 unconsumed partials exist for a job, whoever
committed the last one atomically claims 5 and enqueues a reduce ("eager pairing").
In the tail — no other tasks in flight — allow fan-in 2–4 ("drain mode") so the last
partials never wait for siblings that will never come. Fan-in analysis: total reduce
reads = 8 MB·L·k/(k−1), decreasing in k, so k=5 in steady state (~200 GB, ~5k tasks)
beats k=2 (~320 GB, ~20k tasks); drain mode adds at most ~7 extra reduces (<0.15%) to
remove an unbounded stall.

One subtlety makes this safe: the pairing step is **serialised per job** with an
advisory lock. Without it, two workers committing simultaneously could each see the
other's task as still running and each undercount the partial set — both decline to
pair, and since pairing only runs on partial commit, the job would strand its last
partials forever. The lock costs milliseconds and turns the completion argument (Q8)
into a proof.

**Frozen:** eager, adaptive fan-in; pairing serialised per job.
→ [DM-002](itds/DM-002-work-distribution-stragglers.md), [LLD §4](03-lld.md)

## Q7 — Workers run at wildly different speeds. How do I keep the fast ones busy and stop the slow ones from hurting the job?

Never assign — let workers **pull**. A pull queue is work-conserving: a worker holds
work only while executing it, so a 3× faster worker simply claims 3× as often, with no
speed estimation, no rebalancing, no scheduler component. A slow-but-alive worker's
blast radius is exactly **one task** (~seconds), independent of F — under push it
would be ~1/W of the job. Combined with eager reduction (fast workers reduce while
slow ones still map) and drain mode (no tail stall), idle time exists only when zero
eligible tasks exist system-wide. Speculative re-execution of tail tasks (LATE-style)
is documented as an evolution; leases already bound the crash case, and duplicating
40 MB reads to shave the last task's latency doesn't pay at this shape.

**Frozen:** pull-based claiming; speculation deferred.
→ [DM-002](itds/DM-002-work-distribution-stragglers.md)

## Q8 — How does the system *know* a job is finished?

By proof, not by counting. Counts are conserved: `map` turns k ≤ 5 files into a
partial with n = k; `reduce` turns partials n₁…n_k into one with Σnᵢ; consumption is
exactly-once (guarded). Hence a job's unconsumed partials always **partition its F
files** — so a lone unconsumed partial with **n = F** cannot appear early and cannot
be missed: it *is* the completed sum. Stated fully, completion is a two-part
predicate: the data proof (n = F) plus a liveness read (no pending/claimed tasks for
the job) that rules out a still-coming generate batch — a task-state *read*, not a
mutable counter, so redelivery can't corrupt it. A task counter can't even be
initialized here: reduce tasks are created dynamically (Q6), and at-least-once
delivery makes decrements unsafe.

**Frozen:** semantic completion inside the committing transaction; counters are
UI-only. → [DM-003](itds/DM-003-job-completion-detection.md)

## Q9 — Which queue: SQS, RabbitMQ, Redis, or Postgres?

Q6 and Q8 created a hard requirement: *{mark ≤5 partials consumed + insert their
reduce task}* and *{commit partial + detect completion}* must each be **atomic**. With
an external broker, either dual-write order fails — commit-then-send strands consumed
partials if the send dies (job hangs silently); send-then-commit lets a reduce run
against unconsumed partials (sums counted twice, result silently wrong). The standard
fix, a transactional outbox, means building a Postgres queue *and also* operating a
broker. Meanwhile the load is trivial by queue standards: ~27k tasks per max job,
I/O-bound seconds each — claim rate well under 1k/s against SKIP LOCKED's 1–10k/s
comfort zone. Leases are a column; fairness is an ORDER BY. SQS's real strengths
(managed, unbounded, built-in DLQs) are conceded, with explicit switch triggers
(sustained >5k tasks/s, cross-region consumers, multi-service fan-out) behind a
`QueueAdapter` seam.

**Frozen:** Postgres 16 `FOR UPDATE SKIP LOCKED`; the tasks table *is* the queue.
→ [DM-004](itds/DM-004-queue-technology.md), claim SQL in [LLD §3](03-lld.md)

## Q10 — Workers will crash mid-task, pause for GC, and get the same task twice. How is the answer still exact?

Stop chasing exactly-once — it doesn't exist across a queue and an object store.
At-least-once **plus idempotent effects** produces the same outcome. Three mechanisms
interlock: **deterministic keys** (a task's output object is named after the task, so
a retry overwrites itself byte-identically — generate uses per-file seeds, so even
input files regenerate exactly); **fenced commits** (each claim mints a `lease_token`;
commit and heartbeat both require `lease_token = mine AND status = 'claimed'`, the
reaper rotates the token on requeue, and an absolute `TASK_DEADLINE` caps even a
wedged-but-heartbeating worker); **uniqueness as idempotency** (`UNIQUE(produced_by)`
means a duplicate commit can't fold the same sums in twice). Liveness: 30 s lease,
10 s heartbeat, 5 s reaper — a crash is detected in ≤35 s; three attempts, then the
task is dead and the job fails loudly.

**Frozen:** at-least-once + idempotency + leases/fencing.
→ [DM-006](itds/DM-006-state-model-failure-handling.md), transactions in [LLD §4](03-lld.md)

## Q11 — A 27,000-task job is running and a 4-task job arrives. Does the small one wait three hours?

Under FIFO, yes — for ~15 seconds of actual work, and adding workers never fixes
ordering. Because the queue is a table (Q9), fairness is expressible *inside the claim
query*: order candidates by (in-flight tasks of that job ASC, task priority, age).
The least-served job always goes first → round-robin effect, starvation-free. Priority
runs `finalize > reduce > map > generate`: reduce depth is the irreducible critical
path while map width is surplus parallelism, and draining reduces frees partial
storage. Cost to the big job: ~0.01% of its worker-seconds.

**Frozen:** fairness as claim ordering. → [DM-007](itds/DM-007-multi-job-fairness.md)

## Q12 — Who creates the F input files in the first place?

Not the API — generating 100k files ≈ 800 GB on the submit path is the central-
accumulator sin at the front door. `generate` tasks (~50 files each, per-file
deterministic seeds) ride the same queue; each spawns its batch's `map` tasks on
completion — the same task-spawns-task mechanism as eager pairing, the same
idempotency discipline. One queue, one state machine, one failure model for all four
task types.

**Frozen:** generation is distributed work. → [DM-001](itds/DM-001-aggregation-topology.md)/[DM-006](itds/DM-006-state-model-failure-handling.md), [LLD §2](03-lld.md)

## Q13 — How does W become configurable through the API? *(bonus 1)*

The API shouldn't spawn processes (stateful, unscalable) and workers shouldn't manage
their own population (who spawns the first?). Standard reconciliation: the API writes
`desired_workers`; a **supervisor** loop converges actual → desired — docker compose
scale locally, `ecs.updateService(desiredCount)` on AWS; same loop, different
actuator. Scale-down drains gracefully (SIGTERM → finish task → commit → exit) with
the lease as backstop, so correctness never depends on the drain. A worker is a
**process**, not a thread pool: numpy releases the GIL so threads would match on
throughput — the deciding argument is blast radius (a fault costs one lease, not T)
and keeping W a single knob. Queue-depth autoscaling is the production evolution,
deliberately not chosen: the requirement is *user-set* W.

**Frozen:** supervisor reconciliation of user-set W.
→ [DM-008](itds/DM-008-worker-pool-w-configurability.md), [HLD §6](02-hld.md)

## Q14 — What should the live UI actually show, and how does it stay live? *(bonus 2)*

The flow is strictly server→client, so **SSE** over WebSockets: plain HTTP, built-in
auto-reconnect, and `Last-Event-ID` replay that a BIGSERIAL event id turns into a
one-line `WHERE id > cursor`; polling stays as fallback. An append-only `events` table
feeds it; noisy task-level events fold into a 1 Hz snapshot so ten open tabs cost one
query per second. The non-obvious part is the **progress bar**: `done/total` tasks
*moves backwards* whenever eager pairing creates a new reduce task — so progress is
**file coverage**, `(mapped_files + reduce_inputs_consumed)/(F + R_est)`, monotone
because it is computed from idempotently-keyed partial rows (state, not events),
clamped at 99% so only `finalize` — the completion proof itself — writes 100%.

**Frozen:** events + SSE + coverage-based monotone progress.
→ [DM-009](itds/DM-009-observability-ui.md), API surface in [LLD §6](03-lld.md)

## Q15 — Did distributing the sum cost any accuracy?

No — and the honest version of the claim matters. The 5-ary tree *is* pairwise
summation: error O(log₅F·ε) ≈ 8.9×10⁻¹⁶ at F=100k, the same character as numpy's own
internal pairwise reduction — so distribution is **accuracy-neutral** versus the
realistic single-node baseline. The dramatic ~10⁴× gap (vs ≈1.1×10⁻¹¹) exists only
against a hand-written naive serial loop, whose accumulator grows to ~10⁵ while
addends stay O(1). Kahan compensation was evaluated and rejected — it doubles partial
size and level-0 traffic to buy a digit these bounds don't need — and is the named
mitigation if value bounds ever widen.

**Frozen:** float64 + tree; accuracy-neutral by construction.
→ [DM-010](itds/DM-010-numerical-correctness.md)

## Q16 — How does this run on AWS, and what breaks first at 10×?

Same containers, config-only swap: ECS Fargate (api + worker services), RDS Postgres
Multi-AZ, S3, ALB; the supervisor actuates `desiredCount`. Pre-committed responses to
growth: task rate >5k/s sustained → SQS + outbox ([DM-004](itds/DM-004-queue-technology.md));
C > 10⁸ → column-chunking *within* tasks ([DM-001](itds/DM-001-aggregation-topology.md));
thousands of workers → PgBouncer, then the SQS move; bit-reproducibility requirement →
pinned tree ([DM-010](itds/DM-010-numerical-correctness.md)). → [HLD §6, §8](02-hld.md)

---

## Traceability to the brief

| Brief's criterion | Question | Frozen in |
|---|---|---|
| F > 5: no 1:1 job↔queue item | Q4, Q6, Q12 | DM-001/002, LLD §2 |
| Efficiency of task distribution | Q6, Q7, Q11 | DM-002, DM-007 |
| How the system decides a job is finished | Q8 | DM-003 |
| Multiple jobs submitted while others run | Q11 | DM-007 |
| Minimal idling with heterogeneous workers | Q6, Q7 | DM-002 |
| Combining worker outputs into the final file | Q3, Q4, Q15 | DM-001, DM-010 |
| **Bonus:** W configurable via API | Q13 | DM-008 |
| **Bonus:** UI with live system state | Q14 | DM-009 |
| Components: Node/Express/TS API, DB, queue, Python workers | Q1, Q2, Q9 | HLD §2, LLD §5–6 |

## The one-breath version

> Element-wise mean is a monoid fold, so workers exchange (sum, count) partials that
> any worker can merge in any order; the 5-file RAM limit applies to partials too,
> forcing a 5-ary reduction tree that is never pre-built — reduces are enqueued
> eagerly as partials appear, so fast workers reduce while slow ones map. Completion
> is the conservation proof that a lone partial with count = F is the answer. The
> queue is Postgres SKIP LOCKED because consume-and-enqueue must be one transaction;
> retries are harmless because every output key is deterministic; fairness is an
> ORDER BY; W is a supervisor reconciling a number the API writes; and the UI streams
> SSE with a progress bar that cannot move backwards.
