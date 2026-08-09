# ITD: DM-007 — Multi-Job Fairness via Claim-Query Ordering

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-002, DM-003, DM-004, DM-005, DM-006, `../02-hld.md`, `../CONTEXT-BRIEF.md`
**Simulation:** [Design Lab — Fairness tab](../simulator.html) — FIFO convoy vs least-in-flight with a big and a small job.

---

## Problem Statement

The brief lists "support submitting multiple jobs even if there are ongoing jobs" as one of
four named a critical aspect in the brief aspects, and the envelope makes the failure mode concrete: a max job
(F=100k, C=1M) enqueues ≈25k compute tasks plus ≈2k `generate` tasks, while a small job
(F=3) enqueues 1 `generate` task, 1 `map` task and 1 `finalize` task. Under any
arrival-ordered discipline the small job's three tasks sit behind ~27,000 others. At W=10
workers and ~5 s per task that is 27,000 × 5 s ÷ 10 ≈ 3.75 hours of queueing for a job whose
own work is roughly 15 seconds — a slowdown factor of ~900×. The target is that a small job
submitted behind a max job completes in seconds-to-minutes rather than hours, that the large
job's total makespan degrades only proportionally to the capacity it lends out, and that no
job of any size can be starved indefinitely.

---

## Context

What the decision has to fit inside:

- **W is system-level, not per-job.** The brief states this explicitly: workers are a fleet
  shared across all jobs, not partitioned per job. So fairness is a *scheduling* question
  about which task the next free worker takes — there is no allocation knob to turn.
- **D4 / pull-based distribution (DM-002, DM-003).** Nothing is pushed to a worker; a free
  worker claims. Therefore the entire scheduling policy lives in one place: the claim query.
  There is no central scheduler that could hold a policy, and adding one would reintroduce
  the single-node coordination point D1 rejected.
- **D5 / the `tasks` table is the queue, claimed with `FOR UPDATE SKIP LOCKED`
  (DM-004).** The queue is a SQL table, so ordering policy is an `ORDER BY` — arbitrarily
  expressive, transactional, and changeable without touching a broker. This is the single
  largest reason the chosen option is nearly free; on a FIFO broker like SQS it would not be
  available at all.
- **D3 / eager pairing (DM-002).** Reduce tasks are created on partial commit whenever ≥5
  unconsumed partials exist, and in drain mode with fan-in 2–4. This continuously
  replenishes reduce work throughout a job's life, which matters below: a priority rule that
  prefers `reduce` is only useful if reduce tasks actually exist to be preferred.
- **D6 / partials are 8 MB objects (DM-005).** Unconsumed partials are held storage. At the
  envelope, 20,000 leaf (level-0) partials × 8 MB ≈ 160 GB of live intermediate state if reduce work is
  allowed to lag behind map work — which turns "prefer reduce" from an aesthetic choice into
  a resource-footprint control.
- **D7 / at-least-once with capped attempts (DM-006).** Requeued tasks re-enter the same
  ordering. A retry must not be permanently outranked by fresher work, or attempts get
  consumed by starvation instead of by real failures.
- **Envelope reference point:** ≈25k compute tasks + ≈2k `generate` tasks per max job;
  ⌈F/5⌉ = 20,000 leaf `map` tasks; ≈5,000 reduce tasks over ~7 levels.

---

## Alternatives

### Strict global FIFO (single queue, oldest task first)

One queue for all jobs; the next free worker takes the globally oldest `pending` task.

**Pros:**
- Trivially simple and the default behaviour of almost every broker — with SQS, `ORDER BY`
  is not even offered, so FIFO-ish is what you get.
- Optimal *mean* completion time is not the goal, but FIFO does give the best possible
  makespan for the head job, and zero scheduling overhead.
- Perfectly predictable and easy to explain to a user: submitted first, finished first.

**Cons:**
- Convoy starvation, quantified: 27,000 tasks ahead × ~5 s ÷ 10 workers ≈ 3.75 h of pure
  queueing for a 3-task job whose intrinsic work is ~15 s. A ~900× slowdown on the small
  job, which is a functional failure of an explicit requirement in the brief, not a tuning issue.
- The pathology worsens with fleet size in the wrong direction: adding workers shortens the
  convoy but never reorders it, so no amount of capacity fixes head-of-line blocking.
- Interacts badly with D3: a job's `finalize` task is created last and is therefore the
  newest task in the system, so FIFO systematically schedules the one task that would let a
  user see a result *last* — the exact inversion of what a user waits on.

### Per-job queues with a round-robin consumer

One queue per active job; a dispatcher (or each worker) rotates across job queues.

**Pros:**
- Fairness is structural rather than emergent — a job physically cannot consume more than
  its turn, which is easier to prove correct than a comparative `ORDER BY`.
- Per-job isolation for free: a job with poison tasks or a pathological retry loop cannot
  pollute other jobs' ordering.
- Natural place to hang per-job rate limits or quotas later.

**Cons:**
- Queues become dynamic infrastructure. Jobs arrive and finish continuously, so the system
  must create, discover, and garbage-collect queues — with SQS that is real API surface and
  real lifecycle bugs (leaked queues, workers polling a queue for a job that finished).
- Round-robin over N queues requires either a shared rotation cursor (a new contended
  coordination point, precisely what D4 avoids) or independent random probing by each
  worker, which wastes empty polls: with 50 active jobs of which 3 have work, most probes
  return nothing.
- Weakens D5's central benefit. The claim-and-enqueue transaction of D3 spans the partial
  commit and the reduce enqueue; with per-job queues in a separate broker that becomes a
  dual write across two systems — the bug class D5 exists to eliminate.
- Round-robin over *tasks* is also the wrong granularity for our task mix: it would give a
  `generate` task the same turn as a `finalize` task, ignoring that they sit at opposite
  ends of the critical path.

### Fairness via claim-query ordering — **CHOSEN**

Keep one queue (the `tasks` table). The `FOR UPDATE SKIP LOCKED` claim query orders
candidates by `(in-flight tasks of that job ASC, task priority, age ASC)`, where priority is
`finalize` > `reduce` > `map` > `generate`.

**Pros:**
- Zero new infrastructure: the policy is three terms in an `ORDER BY` on a table that
  already exists. It ships in the same transaction as the claim, so it cannot desynchronise
  from task state.
- Expressive enough to encode both dimensions of fairness at once — *across* jobs (in-flight
  count) and *within* a job (task-type priority) — which per-job queues cannot do without a
  second mechanism.
- Self-correcting and stateless: the in-flight count is derived from current task state, so
  there is no fairness ledger to maintain, drift, or reset when a worker dies. A crashed
  worker's task leaving `claimed` (D7, DM-006) automatically restores that job's fairness
  standing.
- Tunable without redeployment of workers: the policy is server-side SQL.

**Cons:**
- Fairness is *approximate*. It equalises concurrent in-flight tasks, not CPU-seconds, so a
  job whose tasks are systematically slower gets more machine time for the same in-flight
  count. With uniform C per job the skew is small, but it is real.
- Cost is on the hot path: the claim query now sorts candidates instead of taking the head,
  and needs an aggregate over in-flight tasks per job. Requires deliberate indexing
  (`tasks(job_id, status)` plus a maintained per-job in-flight counter) or it becomes the
  bottleneck at high task rates.
- Higher lock contention among concurrent claimers than FIFO, because all workers converge
  on the same small preferred set; mitigated by `SKIP LOCKED` but not eliminated.
- Harder to explain to a user than FIFO, and the completion order is not the submission
  order.

### Weighted fair queuing with user-settable job priorities

Give each job a weight or priority class; allocate worker slots proportionally.

**Pros:**
- The correct long-term answer for a multi-tenant system: lets an operator express that a
  paying tenant's job or an interactive job outranks a nightly batch.
- Deficit-round-robin-style accounting can track *actual service consumed* (CPU-seconds,
  bytes read) rather than in-flight count, fixing the approximation weakness above.
- Composes with the chosen mechanism — a weight is one more term in the same `ORDER BY`.

**Cons:**
- Requires product semantics that do not exist in v1: there is no tenant model, no billing
  tier, and no authenticated user, so any weight would be an unvalidated client-supplied
  integer — an obvious priority-inflation vector where every caller sets max.
- Weighted schemes need anti-starvation machinery of their own (ageing, minimum service
  guarantees) or a high-weight stream starves everything, which is the problem we started
  with.
- Deficit accounting means persisting per-job service counters and deciding their decay —
  meaningful state for a benefit no current requirement asks for.
- Documented as the evolution path, not current scope.

### Admission control / concurrency cap per job

Let jobs run FIFO but cap how many tasks of one job may be in flight (e.g. ≤ ⌈W/2⌉).

**Pros:**
- Very cheap: one predicate in the claim query, no ordering change, and it directly bounds
  the worst-case convoy.
- Guarantees headroom for arriving jobs regardless of how large the incumbent is.

**Cons:**
- Wastes the fleet in the common single-job case: with one max job and W=10, a cap of 5
  idles half the fleet, directly violating the brief's "workers spend as little time as
  possible idling".
- The correct cap depends on the number of active jobs, which is dynamic — so the cap has to
  be recomputed continuously, at which point it *is* the in-flight-count ordering, only
  expressed as a hard bound instead of a soft preference and with an idling failure mode the
  soft version does not have.
- Still leaves within-job ordering unsolved (`finalize` last), because it changes how many,
  not which.

---

## Chosen: Fairness via claim-query ordering

**The decision.** One queue. A free worker claims with:

```sql
WITH inflight AS (
  SELECT job_id, count(*) AS n FROM tasks WHERE status = 'claimed' GROUP BY job_id)
SELECT t.* FROM tasks t
JOIN jobs j ON j.id = t.job_id
LEFT JOIN inflight i ON i.job_id = t.job_id
WHERE t.status = 'pending' AND j.status IN ('running','finalizing')
ORDER BY coalesce(i.n, 0) ASC,          -- 1. fairness across jobs
         t.priority ASC,                 -- 2. priority ASC: finalize=0 first, then reduce=1, map=2, generate=3
         t.created_at ASC                -- 3. age, within a job
FOR UPDATE SKIP LOCKED LIMIT 1;
```

Three terms, in this order, each doing a distinct job. **Note the sort direction on term 2.**
`priority` is stored ascending-urgent — `finalize=0 < reduce=1 < map=2 < generate=3` (LLD §1) —
so the correct clause is `priority ASC`. Writing `DESC` while describing the policy as
"finalize > reduce > map > generate" reads plausibly and inverts the entire ordering: generate
tasks would be claimed first and `finalize` last, which is precisely the FIFO pathology this
ITD rejects. The prose ordering and the SQL direction are opposite by construction; the column
comment in the DDL carries the numbering so the two cannot drift apart again.

**Term 1 — in-flight count ASC: fairness across jobs.** This is least-attained-service
scheduling with in-flight task count as the service proxy. Its effect on the motivating
scenario: the max job saturates the fleet at 10 in-flight tasks; the small job's `generate`
task has in-flight 0, so the *next* worker to free up takes it — not the 27,000th. Expected
wait is one task duration (~5 s), not 3.75 hours. That is a ~2,700× improvement on the small
job's completion time in exchange for the large job losing one worker-slot for the duration
of three tasks: its makespan grows by ~15 worker-seconds out of ~135,000 (≈0.01%). The
asymmetry of that trade is the whole case for the decision.

**Term 2 — priority `finalize` > `reduce` > `map` > `generate`: correct within a job.** Each
step of the ordering earns its place for a different reason:

- **`finalize` first** because exactly one exists per job, it takes seconds, and it is the
  only task whose completion is observable by the user. Delaying it holds a human waiting
  behind machine work; running it first costs the fleet one worker-slot once per job.
- **`reduce` second** for two independent reasons. *Critical path:* the reduce tree is ~7
  levels deep and strictly sequential in depth — a level-k partial cannot exist until its
  children do — so at the envelope the tree contributes ~7 serialised task latencies that no
  amount of extra workers can parallelise away. Leaf `map` tasks, by contrast, are 20,000
  fully independent units: pure width, zero depth. Every second a claimable reduce task
  waits is a second added to the critical path; a `map` task waiting merely shifts which
  worker does it. *Storage:* per D6 a partial is 8 MB and a reduce consumes 2–5 of them to
  produce 1, so reducing is the only operation that shrinks the intermediate footprint.
  Deferring reduces lets unconsumed partials accumulate toward the 160 GB worst case
  (20,000 × 8 MB); preferring them keeps the frontier narrow. Both arguments point the same
  way, which is why this term is robust to a "why not prefer map, to get more parallelism?"
  probe — extra map parallelism buys width we already have in surplus and pays for it in
  depth and storage.
- **`map` third** because a map task's output is a partial, i.e. it *creates* reduce work.
  It must outrank `generate` so that the reduce frontier stays fed rather than the system
  spending all its capacity manufacturing input.
- **`generate` last** because it is the most parallelisable and least urgent work in the
  system: ≈2,000 mutually independent tasks (D9), no downstream task is waiting on any
  *specific* one, and its only role is to keep the map frontier non-empty. Deferring
  generate is also the mechanism that stops a job from materialising 800 GB of input before
  consuming any of it. The one thing we must avoid is deferring it so hard that the map
  frontier empties — which cannot happen here, because when no map or reduce task is
  `pending` the generate tasks *are* the only candidates and get claimed immediately. Strict
  priority is safe precisely because it is only consulted among simultaneously-claimable
  tasks.

**Term 3 — age ASC: FIFO within a (job, priority) class.** This preserves the one genuinely
good property of FIFO — no task is passed over forever by fresher siblings — at the level
where it costs nothing. It also matters for D7 (DM-006): a requeued task keeps its original
`created_at`, so a retry sorts *ahead* of newer tasks in its class rather than behind them.
Attempts are then spent on real failures, not on starvation.

**Interaction with D3 (eager pairing), which makes term 2 effective.** A priority rule that
prefers reduce work is inert if reduce work does not exist. D3 supplies it continuously:
every partial commit checks for ≥5 unconsumed partials and enqueues a reduce inside the same
transaction, and in the tail it drains with fan-in 2–4. So reduce tasks appear throughout a
job's life rather than in seven discrete barrier-separated waves. The two decisions are
mutually reinforcing: D3 keeps the reduce frontier populated, and D8's priority ensures the
fleet consumes it promptly, which in turn frees partials and triggers the next round of
eager pairing. Under a two-phase barrier topology (rejected in D1) this priority term would
be almost meaningless, since no reduce task would be claimable until every map task had
finished.

**Starvation-freedom.** The argument is short and does not depend on task durations:

1. Every `claimed` task leaves the `claimed` status in bounded time — it commits, it fails, or
   its lease expires within 30 s and the reaper requeues it (D7, DM-006). There is no way for
   a task to remain in flight forever, so a job's in-flight count cannot be pinned high
   indefinitely.
2. A job with a `pending` task and in-flight count 0 has the minimum possible value of
   term 1, so it is at the front of the ordering and is claimed by the very next free worker
   — bounded by one task duration, and by definition not blocked behind the incumbent's
   remaining queue depth.
3. Therefore a job's in-flight count oscillates and its `pending` tasks are claimed within
   O(one task duration) of the fleet having capacity; no job's wait is a function of another
   job's *queue depth*, only of the fleet's throughput. The ~900× convoy slowdown is
   structurally eliminated rather than merely reduced.
4. Within a job, term 2 is a bounded strict priority over four fixed classes, and each class
   is drained in age order by term 3. Higher-priority classes are finite and self-liquidating
   (`finalize` is one task; `reduce` tasks are created only by consuming partials, so they
   cannot be manufactured without map output), so a lower class cannot be starved by an
   unbounded stream of higher-priority work. This is the standard hazard of strict priority
   and our task DAG's shape is what defuses it.

The argument depends on one implementation property that is easy to lose in an optimisation:
**the in-flight counts must be computed fresh on every claim.** The CTE form above (and the
correlated-subquery form in LLD §3) evaluates `count(*) … WHERE status='claimed'` inside the
claiming transaction, so step 2 is true of the fleet's *current* state. Cache or materialise
those counts — the documented evolution when the aggregate becomes hot — and staleness enters
the fairness term directly: a job whose tasks all just finished would still sort as though it
held W tasks in flight, and step 2's "claimed by the very next free worker" degrades to
"claimed within one counter-refresh interval". That is an acceptable trade at high task rates,
but it must be made deliberately, with the refresh interval treated as the new starvation
bound rather than assumed away.

**Why each rejection, specifically.** *Strict FIFO* was rejected on the quantified convoy:
3.75 h of queueing for 15 s of work, unfixable by adding workers, and it schedules `finalize`
last by construction. *Per-job queues* were rejected because dynamic queue lifecycle plus
either a shared rotation cursor (new coordination point) or wasteful empty probing is more
moving parts than an `ORDER BY`, and moving the queue out of Postgres would break D3's
atomic claim-and-enqueue into a dual write. *Weighted fair queuing* was rejected as
premature: there is no tenant, billing, or auth model to source weights from, so it would be
client-declared priority with the predictable inflation, plus its own anti-starvation
machinery — it is the documented evolution, and it slots into the same `ORDER BY` when
product semantics exist. *Per-job concurrency caps* were rejected because they idle the fleet
in the single-job case (violating the brief's anti-idling requirement) and, once made
adaptive, degenerate into the chosen ordering with a worse failure mode.

**Failure condition.** Revisit if: (a) the claim query becomes the throughput bottleneck —
p99 claim latency > 50 ms or claim contention visibly idling workers — at which point the
per-job in-flight aggregate moves to a maintained counter column on `jobs`, or the ordering
moves behind the `QueueAdapter` boundary to a real scheduler (D5's documented switch trigger
is sustained >5k tasks/sec); (b) the number of simultaneously active jobs exceeds ~100, where
equalising in-flight counts across 100 jobs on W=10 workers means most jobs hold 0 in flight
and the ordering degenerates toward round-robin-per-task, thrashing the object-store read
cache — admission control (cap on *concurrently running* jobs, not on tasks per job) becomes
the better tool; (c) per-job task cost becomes strongly heterogeneous — jobs with very
different C, so in-flight count stops proxying service — requiring a service-time-weighted
term; (d) a real tenant/priority model appears, which is the direct trigger for the WFQ
evolution; (e) measured small-job completion time behind a max job exceeds ~60 s, which
would falsify the core claim of this ITD.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Small job behind a large job | F=3 job submitted while an F=1,000 job is mid-flight completes in < 30 s (vs ~hours under FIFO) | Integration test; wall-clock from submit to result-object PUT, recorded in the `events` table |
| Large-job makespan cost of fairness | Max-job makespan degrades < 5% when 3 small jobs are interleaved | A/B run: max job alone vs max job + 3 interleaved small jobs |
| Concurrent progress, not serialisation | With 3 jobs active, all 3 show monotonically rising progress % in the same 60 s window | SSE progress stream (D11, DM-009) sampled during the run |
| No starvation | Over a 30-minute soak with continuous mixed-size submissions, max per-job queueing time for any task < 5 × median | Percentile report over `claimed_at − created_at` per task |
| Fleet not idled by fairness | Worker utilisation > 90% while any `pending` task exists | Worker busy/idle events (D11, DM-009) aggregated over the run |
| Priority ordering holds | `finalize` claimed within one task duration of becoming `pending` in ≥99% of jobs; no `reduce` task waits while a `generate` task of the same job is claimed | Event-log audit of claim order vs task type |
| Reduce frontier stays narrow | Peak unconsumed partials ≤ 2 × K × W (i.e. reduce keeps pace with map, well under the 160 GB worst case) | Max of `count(*) FROM partials WHERE consumed_by IS NULL` sampled per second |
| Claim query cost | p99 claim latency < 50 ms at 1k tasks/sec with 10k `pending` rows | `pg_stat_statements` plus worker-side claim timing histogram |
| Retry not starved | A requeued task (D7) is re-claimed ahead of newer tasks in its (job, priority) class in 100% of forced-expiry tests | Chaos test with reaper interval 0; assert claim order by `created_at` |
