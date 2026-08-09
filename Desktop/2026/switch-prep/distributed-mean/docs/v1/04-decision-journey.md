# Distributed Mean — The Decision Journey (v1)

**Date:** 2026-08-10 · **Author:** Samkit Shah · **Status:** v1
**What this is:** the incremental narrative of how the design was derived — each step
states the question that was open at that moment, the shortest honest proof of the
answer, and the decision record that freezes it. Read it top to bottom and you re-derive
the whole system; each step only depends on the ones above it. Inline refs point to the
full arguments: [DM-00X](itds/) for the decision records, [HLD](02-hld.md) / [LLD](03-lld.md)
for the resulting structure.

The interviewer's rubric (four "critical aspects" + two bonuses) is mapped at the end.

---

## Step 0 — Name the problem before designing anything

**Question:** what *is* this computationally, under the wrapper of API/queue/workers?

**Reasoning:** `output[i] = (Σ_f file_f[i]) / F`. Division by a constant commutes with
everything, so the hard part is a **big sum** — and summation over float64 vectors is
**associative and commutative** (a commutative monoid, up to rounding). Problems built
on a monoid admit *tree-shaped, order-free, coordinator-free* aggregation. That single
algebraic observation is the seed of every decision that follows.

**Decision frozen:** treat the job as a distributed fold; design for the monoid, not
for "files". → framing in [HLD §1](02-hld.md), requirements in [01 §1–2](01-requirements-and-assumptions.md)

## Step 1 — Size it before shaping it

**Question:** what do the extremes (F<100k, C<1M) actually imply?

**Reasoning (back-of-envelope):** 10¹¹ float64 ≈ **800 GB** input; one file or one
partial result = **8 MB**; ⌈F/5⌉ = **20,000** leaf work units. Two immovable
consequences: (a) *no single node may stream the whole dataset* — 800 GB through one
NIC is a serial floor; (b) *the queue cannot carry data* — 8 MB ≫ any sane message
size (SQS caps at 256 KB). So: control plane moves references, data plane moves bytes.

**Decision frozen:** control/data plane split. → [01 §4](01-requirements-and-assumptions.md), [HLD §2](02-hld.md), [DM-005](itds/DM-005-data-placement-and-format.md)

## Step 2 — What travels between workers: sums, never means

**Question:** what does a worker's partial output carry?

**Proof that means are wrong:** mean-of-means is only correct when groups are equal
size. F = 12 splits 5+5+2; ten files of 0.0 and two of 1.0 give true mean 2/12 = 0.1667
but mean-of-means (0+0+1)/3 = 0.3333 — silently 2× off. Since F is user-chosen, unequal
groups are *normal*, not edge. Carrying `(sum_vector, count)` makes weighting
structural: any grouping, any order, same answer. Divide by F exactly once, at the end.

**Decision frozen:** partials = `(Σ, n)`; single division in `finalize`.
→ [DM-001](itds/DM-001-aggregation-topology.md) (the counterexample), [DM-010](itds/DM-010-numerical-correctness.md) (why float64 suffices: values ∈ [0,1) ⇒ max Σ = 10⁵ ≪ 2⁵³)

## Step 3 — The constraint is self-similar: reduction must recurse

**Question:** 20,000 partials exist; who combines them?

**Reasoning:** a partial is C float64s = 8 MB — *exactly file-shaped*. So the "≤5 files
at a time" RAM constraint binds reducers the same way it binds mappers. Combining
20,000 partials therefore needs a **5-ary tree**: 20k → 4k → 800 → 160 → 32 → 7 → 2 → 1,
**7 levels, ≈5,000 reduce tasks**. Depth grows as log₅F — raising the F cap 5× costs
one level. There is no legal flat design; recursion is forced, not chosen.

**Decision frozen:** recursive 5-ary reduction. → [DM-001](itds/DM-001-aggregation-topology.md)

## Step 4 — Kill the two tempting shortcuts, for the right reasons

**Question:** why not (a) map-all-then-reduce with a barrier, or (b) one central
accumulator streaming `acc += partial`?

**Reasoning:**
- *Barrier:* the slowest of 20,000 maps gates every reduce; the prompt explicitly makes
  worker speeds heterogeneous, so the barrier converts the slowest worker into the
  job's clock. And it buys nothing — phase 2 still needs the same 5-ary tree.
- *Central accumulator:* the honest analysis first — memory is **not** the objection
  (the accumulator is O(C) = 8 MB). The objection is **bandwidth**: all 160 GB of
  level-0 partials must cross one NIC (~21 min at 1 Gbps) — an Amdahl serial floor
  workers can't shrink — and it makes the API stateful, breaking restarts and
  multi-instance deployment. It also defeats the *purpose* of the 5-file constraint
  while honoring its letter.

**Decision frozen:** neither; the tree runs *through the queue* as ordinary tasks.
→ [DM-001](itds/DM-001-aggregation-topology.md) (both rejections quantified)

## Step 5 — Don't build the tree; let it emerge (the straggler answer)

**Question:** is the reduce tree planned at submit time, or discovered?

**Reasoning:** a planned tree wires reduce X to five *named* children; one slow child
stalls the branch even with 50 other partials ready — the barrier problem reborn at
every internal node. But Step 0 says any partials are combinable. So: **eager pairing**
— whenever ≥5 unconsumed partials exist for a job, whoever committed the last one
atomically claims 5 and enqueues a reduce. In the tail (no other tasks in flight),
allow fan-in 2–4 ("drain mode") so the last stragglers never wait for peers that will
never come. Fan-in analysis: total reduce reads = 8 MB·L·k/(k−1) — decreasing in k, so
k=5 in steady state (≈200 GB, ~5k tasks) beats k=2 (≈320 GB, ~20k tasks); drain mode
adds ≤ ~7 extra reduces (<0.15%) to remove an unbounded stall.

**Combined with pull-based claiming** (workers take work only when free), a slow
worker's blast radius is exactly **one task** (~seconds), independent of F. No speed
estimation, no rebalancing, no scheduler.

**Decision frozen:** pull + eager adaptive fan-in; speculative execution (LATE-style)
documented as evolution, not v1. → [DM-002](itds/DM-002-work-distribution-stragglers.md)

## Step 6 — Completion is a theorem, not a counter

**Question:** how does the system *know* a job is done? (graded aspect #3)

**Proof:** define count-conservation: `map` turns k≤5 files into a partial with n=k;
`reduce` turns partials n₁…n_k into one with Σnᵢ; nothing else creates or destroys
coverage, and the consumed-guard makes consumption exactly-once. Hence the unconsumed
partials of a job always **partition its F files** — so a lone unconsumed partial with
**n = F** is a *proof* the job is complete: it cannot happen early (a count only
reaches F when every file is folded in) and cannot be missed (a partition of size 1
forces n = F). A task counter, by contrast, can't even be initialized — the reduce
count is dynamic (Step 5) — and at-least-once redelivery makes decrements unsafe.

**Decision frozen:** semantic completion inside the same transaction that commits the
final partial; counters demoted to UI-only. → [DM-003](itds/DM-003-job-completion-detection.md)

## Step 7 — The queue is Postgres, because one transaction is the whole ballgame

**Question:** SQS, RabbitMQ, Redis, or Postgres SKIP LOCKED?

**Reasoning:** Steps 5–6 created a hard requirement: *{mark ≤5 partials consumed +
insert reduce task}* and *{commit partial + detect completion}* must be **atomic**.
With an external broker, either order of the dual-write fails: commit-then-send
strands consumed partials if the send dies (job hangs forever, silently);
send-then-commit lets the reduce run against unconsumed partials (sums counted twice,
silently wrong mean). The standard fix — transactional outbox — means building a
Postgres queue *and also* operating a broker. Meanwhile the load is trivially within
Postgres range: ≈27k tasks per max job, I/O-bound seconds each ⇒ claim rate ≪1k/s vs
the ~1–10k/s SKIP LOCKED envelope. Leases are a column; fairness is an ORDER BY.
SQS's real strengths (managed, unbounded, DLQs) are respected — as the documented
switch at >5k tasks/s sustained, cross-region consumers, or multi-service fan-out,
behind a `QueueAdapter` seam.

**Decision frozen:** Postgres 16 `FOR UPDATE SKIP LOCKED`; tasks table *is* the queue.
→ [DM-004](itds/DM-004-queue-technology.md), claim SQL in [LLD §3](03-lld.md)

## Step 8 — Failure model: stop chasing exactly-once; make retries harmless

**Question:** workers crash, pause (GC/VM), and get redelivered — how is the result
still exact?

**Reasoning:** exactly-once across queue + object store doesn't exist; at-least-once +
**idempotent effects** is equivalent in outcome. Three interlocking mechanisms:
1. **Deterministic keys** — output object = `…/partials/{taskId}.f64`; a retry
   overwrites itself byte-identically (generate uses per-file seeds, so even input
   files re-generate identically).
2. **Fenced commits** — each claim mints a `lease_token`; commit is
   `UPDATE … WHERE lease_token = $mine`. A zombie that lost its lease updates 0 rows
   and discards. Fencing is needed *only* at the metadata layer — the data-layer PUT
   was made idempotent by (1), which is why no storage CAS is required.
3. **Uniqueness as idempotency** — `UNIQUE partials(produced_by)` +
   `ON CONFLICT DO NOTHING`: a duplicate commit can't fold the same sums in twice.
Liveness: lease 30 s, heartbeat 10 s, reaper 5 s ⇒ crash detected ≤35 s; 3 attempts
then task `dead`, job `failed` loudly.

**Decision frozen:** at-least-once + idempotency + leases/fencing.
→ [DM-006](itds/DM-006-state-model-failure-handling.md), transactions in [LLD §4](03-lld.md)

## Step 9 — Many jobs at once: fairness is an ORDER BY, not a scheduler

**Question:** a 27k-task job is running; a 4-task job arrives (graded aspect #4).

**Reasoning:** strict FIFO makes the small job wait ~hours for ~15 s of work (~900×
slowdown) — and adding workers never fixes ordering. Because the queue is a table
(Step 7), fairness is expressible *in the claim query*: order candidates by
(in-flight tasks of that job ASC, task priority, age). Least-served job goes first →
round-robin effect, starvation-free (every job's in-flight count eventually reaches
the minimum). Priority `finalize > reduce > map > generate` because reduce depth is
the irreducible critical path while map width is surplus parallelism — and draining
reduces frees partial storage. Cost to the big job: ~0.01% of its worker-seconds.

**Decision frozen:** fairness via claim ordering. → [DM-007](itds/DM-007-multi-job-fairness.md)

## Step 10 — Generation is part of the job, and it's distributed too

**Question:** who writes the F input files? (easy to overlook; F=100k files ≈ 800 GB)

**Reasoning:** if the API generates inputs, submission serializes on one node — the
same sin as the central accumulator, at the front door. So `generate` tasks (~50 files
each, seeded per file for reproducibility) ride the same queue; each spawns its batch's
`map` tasks on completion — same task-spawns-task mechanism as eager pairing, same
dedupe-key idempotency. **The uniformity is the design win: one queue, one state
machine, one failure model for all four task types.**

**Decision frozen:** distributed generation (D9). → context in [DM-001](itds/DM-001-aggregation-topology.md)/[DM-006](itds/DM-006-state-model-failure-handling.md), [LLD §2](03-lld.md)

## Step 11 — Bonus 1: W configurable via the API

**Question (bonus):** "add support for keeping the number of workers (W) configurable
via the API."

**Reasoning:** don't let the API spawn processes (stateful, unscalable) and don't let
workers manage their own population (who spawns the first?). Standard reconciliation:
API writes `desired_workers` to `system_config`; a **supervisor** loop converges actual
→ desired (docker compose scale locally; `ecs.updateService(desiredCount)` on AWS —
same loop, different actuator). Scale-down is graceful: SIGTERM → finish current task →
commit → exit, with the lease path as backstop, so correctness never depends on the
drain. Worker = a **process** (not threads/async): numpy releases the GIL so threads
*would* work — the honest argument is blast radius (a fault costs one lease, not T)
and keeping W a single knob. Queue-depth autoscaling (KEDA/ECS target tracking) is the
production evolution, deliberately not v1: the bonus asks for *user-set* W, and the
straggler demo needs a controlled fleet.

**Decision frozen:** supervisor reconciliation of user-set W.
→ [DM-008](itds/DM-008-worker-pool-w-configurability.md), [HLD §6](02-hld.md)

## Step 12 — Bonus 2: the live UI

**Question (bonus):** "UI with updating logs — workers free/busy, jobs completed,
jobs on the queue…"

**Reasoning:** flow is strictly server→client, so **SSE** over WebSockets (plain HTTP,
built-in auto-reconnect with `Last-Event-ID` — our BIGSERIAL event ids make resume a
one-line `WHERE id > $cursor`); polling kept as fallback. An append-only `events`
table feeds it; noisy task-level events fold into a 1 Hz snapshot frame so ten open
tabs cost one query/sec. The subtle design point is the **progress bar**: `done/total`
tasks *regresses* whenever eager pairing grows the denominator mid-run — so progress is
**file coverage** `(mapped_files + reduce_inputs_consumed)/(F + R_est)`, monotone
because it's computed from idempotently-keyed partial *rows* (state, not events),
clamped at 99% so only `finalize` — the completion proof itself — writes 100%.

**Decision frozen:** events + SSE + coverage-based monotone progress.
→ [DM-009](itds/DM-009-observability-ui.md), API surface in [LLD §6](03-lld.md)

## Step 13 — The free numerical win (say it out loud in the interview)

**Question:** did distributing the sum hurt accuracy?

**Reasoning:** the opposite. Serial accumulation error grows O(F·ε) — the accumulator
grows to ~10⁵ while addends stay O(1), so late addends land on a coarse ulp grid.
The 5-ary tree is **pairwise summation**: O(log₅F·ε) ≈ 8.9e-16 at F=100k vs ≈1.1e-11
serial — ~10⁴× tighter, obtained *for free* from a topology the RAM constraint already
forced. Kahan compensation was evaluated and rejected (doubles partial size and
level-0 traffic to win ~one digit we don't need at these bounds); it is the named
mitigation if value bounds ever widen.

**Decision frozen:** float64 + tree ≻ single-node loop. → [DM-010](itds/DM-010-numerical-correctness.md)

## Step 14 — AWS story and the evolution ladder

Same containers, config-only swap: ECS Fargate (api + worker services), RDS Postgres
Multi-AZ, S3, ALB; supervisor actuates `desiredCount`. What breaks first at 10× and
the pre-committed responses: task rate >5k/s → SQS+outbox ([DM-004](itds/DM-004-queue-technology.md));
C > 10⁸ → column-chunking *within* tasks ([DM-001](itds/DM-001-aggregation-topology.md) failure
condition); thousands of workers → PgBouncer then SQS; reproducibility requirement →
pinned tree ([DM-010](itds/DM-010-numerical-correctness.md)). → [HLD §6, §8](02-hld.md)

---

## Rubric traceability

| Interviewer's criterion | Journey step | Frozen in |
|---|---|---|
| F > 5: no 1:1 job↔queue item | 3, 5, 10 | DM-001/002, LLD §2 |
| Efficient distribution algorithm | 5, 9 | DM-002, DM-007 |
| How the system decides a job is finished | 6 | DM-003 |
| Multiple concurrent jobs | 9 | DM-007 |
| Minimal idling with heterogeneous workers | 5 (pull + eager + drain) | DM-002 |
| Combine worker outputs into final file | 2, 3, 13 | DM-001, DM-010 |
| **Bonus:** W configurable via API | 11 | DM-008 |
| **Bonus:** UI with updating system logs | 12 | DM-009 |
| Components: NodeJS/Express/TS API, DB, queue, Python workers | 1, 7 | HLD §2, LLD §5–6 |

## The one-breath version

> Element-wise mean is a monoid fold, so I ship (sum,count) partials that any worker
> can merge in any order; the 5-file RAM limit applies to partials too, forcing a
> 5-ary reduction tree that I never pre-build — reduces are enqueued eagerly as
> partials appear, so fast workers reduce while slow ones map. Completion is the
> conservation proof that a lone partial with count=F is the answer. The queue is
> Postgres SKIP LOCKED because consume-and-enqueue must be one transaction; retries
> are harmless because every output key is deterministic; fairness is an ORDER BY;
> W is a supervisor reconciling a number the API writes; and the UI streams SSE with
> a progress bar that can't move backwards.
