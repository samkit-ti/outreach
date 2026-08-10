# ITD: DM-002 — Work Distribution & Straggler Mitigation

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001 (aggregation topology), DM-004 (queue substrate), DM-006 (state machine & failure), DM-007 (multi-job fairness), DM-010 (numerics), `../02-hld.md`, `../CONTEXT-BRIEF.md`
**Simulation:** [Design Lab — Scheduling tab](../simulator.html) — pull vs push under heterogeneous speeds; drain-mode off shows the tail deadlock.

---

## Problem Statement

A max job (F = 100k, C = 1M) decomposes into ≈25k compute tasks — ⌈F/5⌉ = 20,000 leaf
`map` tasks plus ≈5,000 `reduce` tasks over ~7 levels and one `finalize` —
against a fleet of W workers that the brief explicitly says "process files at
different speeds". Two things must be decided: **how a task reaches a worker**, and
**how many inputs a task consumes**. The target is that no worker sits idle while any
eligible task exists for any job, and that the job's completion time tracks aggregate
fleet throughput rather than the throughput of its slowest participant. Getting either
wrong is directly visible: with a 3× spread in worker speed and 20,000 leaf tasks, a
distribution scheme that commits work to a worker ahead of time can leave a third of
the fleet idle for the final stretch of every job.

---

## Context

- **K = 5 is a hard ceiling, not a tuning knob.** The RAM constraint ("a worker cannot
  process more than 5 files at a time") caps fan-in for both input files and partials,
  since a partial is file-shaped (C float64s). Any scheme must respect K ≤ 5 at every
  node of the reduction.
- **Task cost is I/O-dominated.** A leaf `map` task reads 5 × 8 MB = 40 MB of float64
  payload (≈95 MB on the wire as CSV, per D6). A `reduce` task reads 2–5 × 8 MB of
  binary partials. Per-task coordination — one `FOR UPDATE SKIP LOCKED` claim, a
  heartbeat, one commit (D5) — is single-digit milliseconds. Coordination overhead is
  therefore well under 1% of task duration at K = 5.
- **Any k partials are interchangeable.** D2 passes `(sum_vector, count)` rather than
  means, so combination is associative *and* commutative. This is the structural fact
  that the whole decision leans on: there is no correctness reason to prefer one
  grouping of partials over another.
- **Multi-job concurrency is evaluated** (critical aspect #4). Whatever distributes work
  must interleave a 25k-task job with a 3-task job without starving either — that
  ordering policy is D8 / DM-007 and is deliberately kept *inside* the claim query
  rather than in a separate placement component.
- **Workers are dumb loops** (D10): claim → heartbeat → execute → commit. W is
  reconciled by a supervisor and is user-configurable (bonus), so fleet membership
  changes underneath any long-running job.
- **Leases already bound the crash case** (D7): `lease_expires_at` plus a reaper
  requeues a dead worker's task — 30 s lease, 10 s heartbeat, 5 s reaper interval, so
  35 s worst-case detection. Straggler mitigation only has to handle the
  *slow-but-alive* worker, which is a strictly smaller problem.

---

## Alternatives

### Push-based assignment by a speed-tracking scheduler

A scheduler component maintains a per-worker throughput estimate (EWMA of recent
tasks/sec) and assigns tasks to specific workers in proportion to their measured
speed, writing `assigned_worker_id` onto the task row.

**Pros:**
- Global view enables *locality-aware* placement: a `reduce` task can be sent to the
  worker that produced one of its input partials, saving an 8 MB fetch per input. At
  ≈5,000 reduce tasks × 8 MB that is a real number (~40 GB of avoidable reads).
- Exact control over policy: deadlines, per-job caps, and reservations are all easy
  when one component decides everything.
- Can batch several tasks per assignment, amortising round-trips (irrelevant at our
  overhead ratio, but it is a genuine property).

**Cons:**
- The estimate is the whole design and it is always stale. Worker speed here varies
  with file size, CPU contention, OS page-cache state, and object-store tail latency —
  none of which the last N tasks predict well. Every mis-estimate converts directly
  into idle time, and the error is unbounded: assign 1/W of 20,000 leaf tasks to a
  worker that turns out 3× slow and you have created the straggler you were trying to
  avoid.
- Correcting a bad assignment requires rebalancing or work-stealing, which is
  pull-based claiming with extra machinery bolted on top.
- The scheduler becomes a stateful, liveness-tracking single point of failure.
  Assignments must be durable or they are lost on scheduler restart — so you rebuild
  leases and a reaper anyway (D7), and now you own both mechanisms.
- W is configurable and reconciled asynchronously (D10). The scheduler must track
  membership changes mid-job; a worker that disappears leaves assigned-but-unclaimed
  work that only the reaper can recover.

### Pull-based claiming over a fixed reduction tree built at submit time

Workers still claim tasks from the queue, but the full task DAG — 20,000 leaves,
≈5,000 reduce nodes, ~7 levels — is materialised when the job is submitted. A reduce
task becomes eligible only once all of its K designated children are `done`.

**Pros:**
- The plan is fully known up front: exact task count, exact tree shape, trivial
  progress percentage, and completion detection collapses to "the root is done".
- **Deterministic grouping.** Because the same partials always combine in the same
  order, float64 results are bit-for-bit reproducible across runs — genuinely valuable
  for testing and for any reproducibility requirement (see DM-010).
- No scheduler component; the DAG is the coordination.
- Dependency edges make the critical path explicit and analysable offline.

**Cons:**
- **One slow child stalls its parent branch.** A parent with 4 of 5 children complete
  cannot start; those four 8 MB partials sit idle as bytes on disk while the fifth
  child runs. The stall then propagates up all ~7 levels — exactly the barrier
  behaviour that D1 rejects in two-phase map-reduce, reintroduced per-node.
- It discards the interchangeability property from D2 for no compensating benefit:
  the tree insists on *which* five partials combine when any five would do.
- The plan is committed before a single task has run, i.e. at the moment of least
  information: nothing is yet known about actual per-worker speeds, per-vector read
  latency, or even whether the job will survive to completion rather than being
  cancelled. A fixed wiring cannot hand a straggler's slot to an idle worker later,
  when that information finally exists.
- Materialising the ≈5,000 reduce rows and the edge set on top of T1's 20,000 `map`
  rows, then storing and traversing that edge set, is state we would otherwise not need.

### Pull-based claiming with eager, adaptive reduction  ← chosen

Nothing is ever assigned. A free worker atomically claims the highest-ranked eligible
task (D8 ordering, `FOR UPDATE SKIP LOCKED`, D5). Reduce work is created *reactively*:
on every successful task commit (and, for reaped tasks that never commit, in the reaper —
see the trigger set below), inside the same transaction, the committer takes a per-job
advisory lock — `pg_advisory_xact_lock(hashtext('pairing'), hashtext(job_id::text))` — and then reads the
job's unconsumed partials with a plain `SELECT … FOR UPDATE ORDER BY created_at` (no
`SKIP LOCKED` on partials). If ≥5 unconsumed partials exist for the job, claim 5 and
enqueue a `reduce`; if the job has no other tasks pending or claimed and ≥2 partials
remain, reduce them at fan-in 2–4 (drain mode); if exactly one partial remains with
`count == F`, enqueue `finalize` (D3).

The advisory lock is the fix for a race that `SKIP LOCKED` on partials actively creates.
Under READ COMMITTED, two T2 commits for the same job each skip the other's locked
partial rows and each still sees the other's task as `claimed`, so **both** undercount
the partial set and **both** decline to pair. Nothing is left to re-trigger pairing, so
≥2 partials are stranded forever — reachable at F = 7 with 2 workers, i.e. not a
theoretical concern. Serialising the pairing step per job means the second committer runs
after the first has committed: it sees the first's new partial and sees the first's task
as `done`, so exactly one of them takes the pairing branch and it does so with a complete
view.

**Pros:**
- Self-balancing under heterogeneity with no estimation of anything (argued below).
- No component to add: the eager-pairing logic rides the transaction that commits the
  partial, and the ordering policy rides the claim query.
- Full fan-in 5 in steady state minimises total reduce work; greedy fan-in in the tail
  minimises tail latency. The two regimes are the right trade in each regime.

**Cons:**
- Reduce grouping is timing-dependent, so results are not bit-for-bit reproducible
  run to run (float64 addition is not associative in the last bits). Accepted; see
  Failure condition.
- The eager-pairing transaction is a contention point: every partial commit touches
  the same job's partial set, and the per-job advisory lock makes that contention
  explicit — pairing is serialised per job, so concurrent committers queue for
  milliseconds instead of racing. That is the price of correctness, and it is cheap: the
  locked section is a small indexed read plus two writes, the lock is per-*job* so
  different jobs never contend, and unconsumed partials per job stay small (D8
  prioritises `reduce` over `map`). Mitigated further by a partial index.
- Progress reporting is harder than with a static DAG — the denominator moves. Handled
  by counters that are explicitly for UI only (D11 / DM-003).

### Add LATE-style speculative execution of tail tasks

On top of pull-based claiming, monitor per-task progress rate and launch a duplicate
copy of tasks projected to finish last, taking whichever copy commits first —
the mechanism from *Improving MapReduce Performance in Heterogeneous Environments*
(Zaharia et al., USENIX OSDI 2008), which replaces Hadoop's progress-threshold
heuristic with an estimated-time-to-completion ranking and reports up to ~2×
improvement in response time in heterogeneous/virtualised clusters.

**Pros:**
- Attacks the one case leases do not: a worker that is alive, heartbeating, and
  running at 20% speed never trips a lease timeout, so D7 will not rescue it.
- Well-studied policy with published tuning (speculative caps, slow-node blacklisting)
  and a directly analogous target environment — heterogeneous workers are precisely
  the condition LATE was written for.
- Our idempotency story already makes duplicates safe: deterministic object keys plus
  atomic PUT (D7) mean a duplicate task overwrites harmlessly, and the consumed-guard
  prevents double-consumption of partials.

**Cons:**
- **Duplicate I/O is expensive here.** Re-running a leaf `map` task means re-reading
  40 MB of payload; even a 10% speculation rate across 20,000 leaves is ~80 GB of
  extra reads on a job whose total input is 800 GB. Speculation trades bandwidth we
  are already bottlenecked on for latency.
- Progress-rate estimation, which is the core of LATE, is weak for our tasks. A leaf
  task is essentially "read 5 files, accumulate" — few reportable phases, so the
  progress score is coarse and the ranking it feeds is noisy.
- **Pull has already collapsed the payoff.** Under push, a slow worker holds ~1/W of
  the job, so its damage scales with F. Under pull it holds exactly one task, so its
  damage is bounded by one task duration (~a second at 40 MB) regardless of F.
  Speculation is then competing for the last few tasks of a job, not for a share of it.
- New tunables (thresholds, speculative caps, blacklisting) that must be justified and
  observed, for a benefit we cannot yet measure.

---

## Chosen: Pull-based claiming with eager, adaptive reduction (D3 + D4)

Workers pull; nothing is ever pushed to a named worker. Reduce tasks are created
eagerly at fan-in 5 in steady state and greedily at fan-in 2–4 in drain mode. LATE-style
speculation is documented as an evolution and is **not** in the current scope.

**How pairing is serialised.** The eager-pairing step at the top of T2 takes a per-job
advisory lock, `pg_advisory_xact_lock(hashtext('pairing'), hashtext(job_id::text))`, and then reads the job's
unconsumed partials with a plain `SELECT … FOR UPDATE ORDER BY created_at` — deliberately
**not** `SKIP LOCKED`. Skipping locked partial rows is what makes two concurrent T2s for
the same job each undercount the partial set (each also still sees the other's task as
`claimed` under READ COMMITTED) and each therefore *decline* to pair, stranding ≥2
partials with nothing left to re-trigger pairing. That is reachable at F = 7 with 2
workers. With the lock, pairing is serialised per job, so concurrent committers queue for
milliseconds instead of racing: the second pairer runs against the first's committed
partial and sees the first's task as `done`, so it has a complete view and exactly one
pairing decision is made per commit. Contention is per-job and negligible — the locked
section is milliseconds, and two different jobs never contend at all. The two-key form
namespaces the lock under `hashtext('pairing')` so it cannot collide with any other
advisory-lock use in the system; within that namespace the job key is an `int4` hash, so
the worst a hash collision can do is make two *unrelated* jobs serialise their pairing
steps for a few milliseconds — a throughput coincidence, never a safety issue, because the
lock's job is to serialise, and serialising more than strictly necessary is harmless.

**What triggers pairing, exhaustively.** Pairing runs (1) in T2 after **every** successful
fenced task-update, and (2) in T3 for **every** job whose task the reaper requeues or kills.
The first is deliberately unconditional: it is tempting to skip pairing when the partial
`INSERT … ON CONFLICT DO NOTHING` matched nothing ("a prior commit already paired"), but a
task reaped *after* inserting its partial and *before* its commit landed will be retried, and
its retry's commit sees exactly that conflict — skip pairing there and the job holds
unconsumed partials with no trigger left. The second exists because a reaped task never
commits at all, so T2's trigger cannot fire for it. Pairing is idempotent under the job lock
(it reads current state and either takes rows or does not), so an unnecessary evaluation
costs one indexed read while a skipped one costs the job. → LLD §4 T2/T3

**Why pull self-balances.** A pull queue is work-conserving by construction: a worker
holds a task only while executing it, so there is no private backlog to be stranded
behind a slow consumer. The number of tasks a worker completes is then automatically
proportional to its throughput — a 3× faster worker claims 3× as often, with no
calibration, no estimate, and no correction loop, and it re-adapts within a single job
if a worker slows mid-flight. This is the classic single-shared-queue versus
queue-per-server result: W independent queues suffer head-of-line blocking and idle
servers next to non-empty queues; one pooled queue cannot. Worst-case idle time drops
from "duration of a mis-assignment" to "one claim round-trip" — single-digit
milliseconds against ~1s tasks, i.e. under 1% of a worker's wall clock.

**Why 5 files per leaf task.** Granularity is bounded above by K = 5 (RAM). Going
*below* 5 is the real question, and it loses on both axes: at 1 file per task we get
100,000 leaf tasks instead of 20,000 — 5× the coordination events — and 5× as many
partials to reduce, deepening the tree. The finer balance it buys is worth nothing
because per-task overhead is already <1% of a task's ~40 MB of I/O; there is no
imbalance left to shave. So K = 5 is taken at the ceiling for `map`.

**Why fan-in 5 minimises total reduce work.** Over L = ⌈F/5⌉ = 20,000 leaf partials, a
k-ary reduction needs ⌈(L−1)/(k−1)⌉ reduce tasks and log_k L levels, and each task
reads k × 8 MB. Total reduce bytes read is therefore 8 MB × L × k/(k−1). The
amplification factor k/(k−1) is strictly decreasing in k, so the largest legal k wins:
k = 5 gives ≈5,000 tasks over ~7 levels and 1.25 × L × 8 MB ≈ 200 GB, while k = 2
gives ≈20,000 tasks over ~15 levels and 2.0 × L × 8 MB ≈ 320 GB. Fan-in 5 is 4× fewer
tasks, half the depth, and 120 GB less reading.

**Why greedy fan-in in the tail minimises latency, and why it is nearly free.** In
steady state, waiting for a 5th partial costs nothing — more are arriving. In the tail
the same wait is pathological: if the job has no other pending or claimed tasks, no
further partials will *ever* arrive, so a strict-5 rule deadlocks and a
wait-with-timeout rule stalls for the timeout. Drain mode reduces whatever is there at
fan-in 2–4 and the wait disappears. The cost is bounded and tiny: drain mode only
triggers once a job has no other work in flight, so it adds at most one extra reduce
per remaining level — ≤ ~7 tasks against ≈5,000, under 0.15% extra reduce work. That is
the whole trade: ~0.15% more work to remove an unbounded stall.

**Why each rejection.** *Push with speed tracking* was rejected because it makes tail
latency a function of estimator accuracy, and our sources of speed variance (page
cache, contention, object-store tails) are not predictable from recent history; its
one real win, locality-aware reduce placement, is recoverable later as a claim-order
hint without giving up pull. *Fixed reduction tree* was rejected because per-node
all-children-complete eligibility is a barrier — the exact failure D1 rejects at the
job level, reinstated ~5,000 times — and because it spends D2's commutativity on
nothing; its reproducibility benefit is real but is not a stated requirement. *LATE-style
speculation* was rejected as premature, not as wrong: leases already bound the crash
case to the lease timeout, drain mode already removes fan-in stalls, and pull already
caps a slow-but-alive worker's blast radius at one task, so speculation would buy tail
latency on the last handful of tasks in exchange for tens of GB of duplicate reads and
a progress-estimation problem our task shape does not support.

**Failure condition.** We revisit if any of:
1. **p99 job completion exceeds 1.5× the time projected from aggregate fleet
   throughput**, and per-task traces attribute it to a slow-but-alive worker on the
   critical path → adopt LATE-style speculation, scoped first to the top ~3 reduce
   levels (≈31 tasks) where duplicate I/O is cheapest.
2. **Worker idle fraction exceeds 5% while eligible tasks exist** → the bottleneck is
   claim contention, not distribution; batch claims or shard the claim query
   (DM-004 territory), do not switch to push.
3. **Bit-for-bit reproducibility becomes a requirement** → eager grouping cannot
   provide it (float64 addition is non-associative in the last bits, so run-to-run
   results may differ by an ULP); the fixed-tree alternative wins outright and we
   switch. See DM-010.
4. **K is relaxed above ~50** → leaf task working set exceeds ~400 MB and a task stops
   being a sensible retry unit; re-derive granularity rather than tracking K.
5. **Cross-node read bandwidth dominates map time** — measured time spent fetching input
   vectors exceeds the accumulate time by a wide margin → add **data locality** as a
   claim-order preference: a worker prefers `map` tasks whose input node is co-located with
   it, falling back to any eligible task so the queue stays work-conserving. Deferred, not
   rejected: it is a hint inside the existing claim query, not a return to push.

---

## Appendix — the chunk-size choice, derived

The fixed 5-file map chunk can be derived rather than asserted. Framed as Q||C_max
(makespan on uniformly-related machines, solved greedily online by the pull queue),
the only free knob is chunk size c, pulled on by two forces:

- **Per-task overhead is O(C), not O(1).** Every task emits a full C-length partial
  (8 MB at C = 10⁶) regardless of how many files it consumed — plus a claim, a commit,
  and an ack. So overhead o ≈ α·C is *constant in c*, and the overhead ratio o/(c·p)
  falls as 1/c: bigger chunks buy real throughput.
- **The straggler tail.** The slowest worker may claim a chunk near the end, putting
  c·p_slowest on the critical path: c ≤ T*/p_slowest, where T* = F/Σ(1/pᵢ) is the
  fluid lower bound.

Balancing the two (homogeneous case) gives the EOQ-shaped square-root rule

    c* = √( F·o / (α·W·p) ) ,   oversubscription K* = N*/W = √((F/W)·(p/o)).

Evaluated at this system's envelope: reading a file (~8 MB) costs about the same as
emitting a partial (~8 MB), so p/o ≈ 1, and at F = 10⁵, W = 100: c* ≈ 32 — clamped by
the RAM cap to **5**. For every realistic job (F ≥ ~5W) the cap binds, c = 5 is
optimal, and oversubscription K = F/(5W) ≫ 1 provides the load balancing for free.

Two facts worth carrying:

1. **The risk curve is asymmetric.** Undershooting c costs a few percent of makespan;
   overshooting costs 50–150% (a slow worker holding an oversized chunk). When in
   doubt, round down.
2. **The small-F regime (F < ~5W) is where the derivation matters.** There the
   straggler ceiling binds: c = clamp(⌈T*/p_slowest⌉, 1, 5), or better, tapered
   speed-proportional dispatch (guided/factoring-style, sizes shrinking with remaining
   work, per-worker speed as an EWMA from a probe pass). Deliberately not built:
   tapering with *unknown* speeds gambles the first dispatch — a slow worker grabbing
   the big opening chunk is the 150% case — whereas pull at fixed c never risks more
   than one chunk. Documented as the small-job evolution, with the ceiling rule as
   its trigger.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Worker idle time while eligible work exists | < 5% of worker wall clock | `workers` heartbeat state sampled from the `events` table (D11); idle intervals correlated against pending-task count |
| Tasks in flight per worker | exactly ≤ 1 at all times | invariant assertion over `tasks` where state = `claimed`, grouped by worker |
| Steady-state reduce fan-in | ≥ 95% of `reduce` tasks consume exactly 5 partials **in steady state**; the sub-5 remainder is drain-mode reduces, which are bounded by tree depth (≤ ~7 per job, < 0.15% of ≈5,000 — see the drain-mode derivation above) rather than by W. Pairing is serialised per job by the advisory lock, so raising W does not add fan-in-<5 reduces. | histogram of consumed-partial count per reduce task, partitioned into steady-state vs drain-mode reduces |
| Drain-mode overhead | extra reduce tasks ≤ tree depth (~7 per job), < 0.15% of ≈5,000 | actual reduce-task count vs ⌈(⌈F/5⌉−1)/4⌉ baseline |
| Straggler sensitivity | job completion time within 1.2× of aggregate-throughput projection with a deliberately 3×-slowed worker in the fleet | injected-slowdown run at F = 1000, compared against homogeneous baseline |
| Tail shape | last task finishes within 2× mean task duration of the second-to-last | per-task timestamps from the `events` table |
