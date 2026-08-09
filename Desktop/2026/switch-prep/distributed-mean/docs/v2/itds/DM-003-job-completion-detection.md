# ITD: DM-003 — Job Completion Detection

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Revision:** v2 — hardened after adversarial review (see ../CHANGELOG.md)
**Related:** DM-001 (aggregation topology), DM-002 (work distribution & stragglers), DM-004 (queue substrate), DM-006 (state machine & failure), DM-007 (multi-job fairness), DM-009 (observability), `../02-hld.md`, `../CONTEXT-BRIEF.md`
**Simulation:** [Design Lab — Topology tab (event log)](https://claude.ai/code/artifact/ee9896b4-7e99-4aeb-b378-33290d2acd41) — the log prints the count==F proof firing at each lane's completion.

---

## Problem Statement

"How the system decides a job is finished" is graded explicitly (critical aspect #3),
and it is hard here for one specific reason: **the task count is not known in advance.**
A max job (F = 100k, C = 1M) produces ≈2k `generate` tasks and ≈25k compute tasks, but
the ≈5,000 `reduce` tasks are created *dynamically* by eager pairing (D3) — how many
there are depends on drain-mode fan-in, which depends on arrival timing, which depends
on heterogeneous worker speeds. Meanwhile the queue is at-least-once (D7), so any
completion signal must be immune to redelivery, and multiple jobs run concurrently
(critical aspect #4), so nothing global may be interpreted as one job's state. We need a
completion test that is a *proof*, evaluated in the same transaction that produces the
last piece of work, with no polling component and no counter that redelivery can corrupt.

---

## Context

- **A partial is `(sum_vector, count)`** where `count` is the number of *input files*
  the partial covers (D2). Never a mean — dividing happens exactly once, in `finalize`.
- **The eager-pairing transaction already exists** (D3). On every partial commit, inside
  the same DB transaction, we take a per-job advisory lock
  (`pg_advisory_xact_lock(hashtext(job_id::text))`) and read the job's unconsumed partials
  with `SELECT … FOR UPDATE ORDER BY created_at` to decide whether to enqueue a `reduce`.
  Completion detection is one more branch in a transaction we are already paying for —
  not a new mechanism.
- **`count == F` is reachable at exactly one moment.** The root of the reduction covers
  all F files; nothing else does.
- **At-least-once delivery is the default** (D7): a task may be redelivered after a
  lease expiry, and a worker may commit output twice. Idempotency comes from
  deterministic object keys + atomic PUT; consuming partials is guarded so a redelivered
  `reduce` cannot double-consume.
- **`tasks` is the queue** (D5), so "no pending or claimed tasks for this job" is a
  plain indexed predicate over the same rows in the same transaction — not a
  cross-system query. This is the structural reason the chosen design costs nothing.
- **Fairness ordering (D8)** prioritises `finalize` > `reduce` > `map` > `generate`, so a
  `finalize` enqueued by this rule is picked up promptly even under multi-job load.
- **A UI is required** (bonus, D11) and wants per-job progress %, which is a different
  requirement from correctness and is deliberately kept separate below.

### The conservation invariant

For any job, at every transaction boundary:

> **Σ count over all unconsumed partials of the job + (files covered by tasks not yet
> committed) = F.**

Each task type preserves the total covered-file count:

- **`generate`** creates files; it adds no partials and changes no count.
- **`map`** consumes k ≤ 5 files and emits one partial with `count = k`.
- **`reduce`** consumes k ∈ [2, 5] partials with counts n₁…n_k, marks them consumed in
  the same transaction, and emits one partial with `count = Σ nᵢ`. Sum in, same sum out.
- **`finalize`** consumes the single `count == F` partial and emits the result file.

Because every `map` output is disjoint in the files it covers (each input file is
assigned to exactly one leaf task) and `reduce` neither drops nor duplicates a partial
(the consumed-guard makes consumption exactly-once per partial), the unconsumed partials
of a job always **partition** the job's F files. Therefore a single unconsumed partial
with `count == F` covers every file exactly once — it *is* the answer's numerator. This
makes `count == F` a **proof of completion, not a heuristic**: it cannot be true early,
because a partial's count only reaches F after all F files have been folded in; and it
cannot be missed, because the counts of a partition must sum to F and a partition of
size 1 forces that element's count to F.

The paired condition "no pending or claimed tasks for this job" is what closes the other
half: it rules out the case where `count == F` is on a partial belonging to a job that
still has `generate` work outstanding for a *later* batch, and it is the same predicate
drain mode already evaluates in D3. Stated plainly, then: completion is a **two-part
predicate** — a data proof (`count == F` on the sole unconsumed partial) plus a liveness
predicate (no pending or claimed tasks for the job) — and the second half is a **read of
task state, not a counter**, which is exactly why at-least-once redelivery cannot corrupt
it.

---

## Alternatives

### Atomic remaining-task counter in the DB (the Celery-chord-with-Redis approach)

Store `remaining_tasks` on the job row (or in Redis), set it to the task count at
submit, and decrement atomically as each task completes. The job is done when it hits
zero. This is how a Celery chord synchronises: the header's task count is written down
and each completing task decrements a Redis counter, with the callback fired by whoever
drives it to zero — with a polling fallback for backends that cannot do the atomic
decrement (see *How Celery Chord Synchronization Works*,
https://blog.untrod.com/2015/03/how-celery-chord-synchronization-works.html).

**Pros:**
- Simple, universally understood, and battle-tested in a widely deployed framework.
- O(1) check with no scan of partials; the trigger is a single atomic operation.
- Gives progress-percentage for free as a by-product of the same number.

**Cons:**
- **It requires knowing the task count up front, and we do not.** Reduce tasks are
  created dynamically by eager pairing (D3), and drain mode can produce a fan-in-2
  reduce where a fan-in-5 was expected, changing the total. A counter initialised at
  submit is wrong by construction. Patching it — incrementing when a reduce is created,
  decrementing when it completes — turns it into a live in-flight counter whose zero
  is racy: it passes through zero between "last map committed" and "eager pairing
  enqueued the reduce", and would fire completion mid-tree.
- **At-least-once delivery makes the decrement unsafe.** A redelivered task must not
  double-decrement, so you need per-task idempotency on the decrement itself: a
  `decremented` flag on the task row, checked and set in the same transaction. At that
  point the counter is derived from task state you already have, and the counter is
  pure duplicated truth that can drift from it.
- Two representations of the same fact (counter and task rows) can disagree; when they
  do, the counter is the one that fires completion, so a drift is a wrong answer rather
  than a wrong dashboard.

### Coordinator/watcher process polling job state

A dedicated process periodically (say every 500 ms) queries each active job for
"partials with `count == F` and no outstanding tasks", and enqueues `finalize`.

**Pros:**
- Cleanly decoupled: workers stay ignorant of job-level semantics.
- Naturally the place to also enforce job timeouts and cancellation.
- Robust to a missed trigger — the next poll catches it, so it is a good *backstop*.

**Cons:**
- Adds up to one poll interval of latency to every job, on top of `finalize` execution.
  With a UI showing live progress, that pause at 100% is exactly what a reviewer notices.
- Introduces a component whose only role is watching, which itself needs liveness,
  leader election (two coordinators must not both enqueue `finalize`), and monitoring.
- Polling cost scales with active jobs × interval whether or not anything changed.
- It is strictly weaker than doing the check in the transaction that changes the state
  being checked: the transaction *knows* the state changed, the poller has to discover it.

### Semantic completion — the `count == F` partial IS the signal  ← chosen

No counter is consulted for correctness. Inside the eager-pairing transaction (D3), when
the job has exactly one unconsumed partial, that partial's `count == F`, and no tasks are
pending or claimed for the job, CAS the job to `finalizing` and enqueue `finalize`.

**Pros:**
- The condition is derived from the data itself and backed by the conservation
  invariant, so it cannot be true early or false late.
- Zero added latency and zero added components: it is a branch in a transaction that
  already runs on every partial commit.
- Redelivery-safe for free, because the consumed-guard already makes it so (below).

**Cons:**
- The check requires reading the job's unconsumed partials — an indexed query, not O(1).
  Bounded and cheap because D8 prioritises `reduce`, keeping the unconsumed set small.
- Completion logic lives in the commit path rather than in one obvious "completion
  service", so it is less discoverable to a new reader. Mitigated by keeping D3's
  transaction in a single named function.
- If the invariant were ever violated by a bug (a lost or duplicated partial), the job
  would hang rather than finish wrong. Preferred failure direction, and covered by an
  alert (Success Metrics).

### Queue-empty detection

Treat "the queue has no messages" as completion.

**Pros:**
- Trivial to implement; on a broker with a reliable depth metric it is one call.
- Fine for a single-job batch system, which is why it shows up in practice.

**Cons:**
- **Wrong under multi-job concurrency**, which is a graded requirement: the queue being
  empty says nothing about *which* job finished, and it is essentially never empty while
  any job runs. Per-job depth filtering just re-derives "no pending tasks for this job",
  i.e. half of the chosen condition, with none of the proof.
- **Racy even for one job.** The queue is empty at the instant a worker has claimed the
  last `map` but has not yet committed its partial — visible depth zero, work
  outstanding. Fixing that means also checking claimed/running tasks, at which point
  you are reading task state, not queue depth.
- Says nothing about *what* to finalize; you still need to find the root partial.

---

## Chosen: Semantic completion via `count == F` (with counters demoted to UI only)

**The decision.** Completion is detected inside the D3 eager-pairing transaction. On
every partial commit, in the same transaction that commits the partial, we evaluate the
job's unconsumed partials:

0. Take the per-job advisory lock `pg_advisory_xact_lock(hashtext(job_id::text))`, then
   read the unconsumed partials with `SELECT … FOR UPDATE ORDER BY created_at`. This
   serialises the whole pairing/completion decision per job.
1. ≥5 unconsumed partials → claim 5, enqueue a `reduce` (steady state).
2. No other tasks pending/claimed for the job and ≥2 partials remain → claim 2–4,
   enqueue a `reduce` (drain mode).
3. **Exactly one unconsumed partial, its `count == F`, and no tasks pending/claimed for
   the job → enqueue `finalize` and move the job to `finalizing`.**

Enqueuing `finalize` is guarded by a **compare-and-swap on the job row**, not by the
in-memory belief that we are the last committer:

```sql
UPDATE jobs SET status = 'finalizing' WHERE id = $j AND status = 'running';
```

If that updates 1 row we own finalization and insert the `finalize` task in the same
transaction. If it updates **0 rows**, someone else already finalized (or the job was
cancelled/failed) and the branch is a no-op. So even a duplicated evaluation of branch 3
can only ever produce one `finalize` task and one result file.

`finalize` divides the sum vector by F exactly once (D2), writes the result CSV (D6),
and transitions the job to `completed`. Progress counters (tasks completed, files covered)
are maintained for the UI via the `events` table and SSE (D11) and are **never** read to
decide completion — they may lag, be double-counted by a redelivery, or be reset without
affecting correctness. That demotion is the point: it removes a whole class of
"the dashboard said 100% but the job never finished" bug by making the dashboard
non-load-bearing.

**Positive case.** This is the only option where the completion test is *entailed* by
the data rather than *tracked alongside* it. The conservation invariant means there is
exactly one moment in a job's life when a single unconsumed partial has `count == F`, and
we evaluate the condition at precisely the moment it can first become true — inside the
commit of the partial that makes it true. That gives three properties simultaneously:
minimum possible latency (no interval, no poll), no new component, and no second
representation of truth that can disagree with the first. It also composes with the
dynamic task count that defeats the counter approach: the condition never mentions how
many tasks there are, so eager pairing and drain-mode fan-in 2–4 (DM-002) change nothing
about it. And it is per-job by construction, so multi-job concurrency is not a special
case.

**How it composes with at-least-once delivery.** A redelivered `reduce` task is the
adversarial case: task R consumed partials p₁…p₅, emitted p₆, committed, and is then
redelivered after a lease expiry (30 s lease, 10 s heartbeat, 5 s reaper → 35 s
worst-case detection; D7). Four guards interlock:

1. **The consumed-guard (D7).** Marking p₁…p₅ consumed happens in the same transaction
   that inserts p₆. The redelivered attempt's conditional claim (`UPDATE … WHERE
   consumed_by IS NULL`) matches zero rows, so it cannot re-consume and cannot mint a
   second p₆. The partition invariant therefore holds per *partial*, not per *delivery*.
2. **Deterministic object keys (D7).** p₆'s bytes are written to a key derived from R's
   task id, with an atomic PUT, so a re-execution that does get as far as writing simply
   overwrites identical content.
3. **The completion condition is a predicate over state, not an event count.** Even if
   the third branch is evaluated twice, it reads the same one-partial-with-`count == F`
   state and reaches the same conclusion — and enqueuing `finalize` is itself guarded by
   the CAS `UPDATE jobs SET status='finalizing' WHERE id=$j AND status='running'`, so a
   duplicate evaluation matches 0 rows and is a no-op rather than a second result file.
   Contrast the counter alternative, where a duplicate *event* is a duplicate decrement
   and permanently corrupts the trigger.
4. **Pairing is serialised per job** (`pg_advisory_xact_lock(hashtext(job_id::text))`, D3).
   Two committing transactions therefore cannot both undercount the partial set and both
   decline — the ELSE branch is only ever taken by the last committer with a complete
   view. Without this, `SKIP LOCKED` on the partials read plus READ COMMITTED lets each of
   two concurrent T2s miss the other's partial *and* see the other's task as still
   `claimed`, so both decline to pair and ≥2 partials strand forever with nothing left to
   re-trigger pairing. The lock removes that state from the reachable set rather than
   detecting it afterwards.

The general shape: **idempotent state predicates survive at-least-once delivery;
mutable event counters do not, without extra per-task bookkeeping.** The advisory lock is
what makes the predicate's *inputs* complete; the CAS is what makes acting on it
single-shot.

**Why each rejection.** *The atomic counter / Celery-chord approach* was rejected
because it needs a known task count and ours is dynamic by design (D3), and because
under at-least-once delivery a safe decrement requires per-task idempotency flags that
make the counter a redundant projection of task state — with the redundancy on the
correctness path. Celery's own polling fallback for backends without atomic decrement is
the tell: the counter is a performance optimisation over a state check, and we can
afford the state check. *A polling coordinator* was rejected because it adds latency
proportional to its interval and a component whose only job is to notice something the
committing transaction already knew, plus leader election to keep two of them from
double-finalizing; it is retained only as an optional low-frequency **backstop** (see
below), never as the primary path. *Queue-empty detection* was rejected because it is
wrong under the graded multi-job requirement and racy even single-job, since depth zero
does not mean claimed-and-uncommitted work is absent.

**Retained backstop (not the primary path).** The reaper (5 s interval, enforcing the 30 s
lease against 10 s heartbeats — D7) also runs a cheap sweep over jobs in state `running`
**or `finalizing`** with zero pending and zero claimed tasks. Under the invariant that set
is always empty: the advisory lock makes the mutual-decline race unreachable, so the sweep
is now genuinely a **bug detector** rather than an aspirational safety net — if it fires,
the pairing guard or the consumed-guard is broken. The `finalizing` case covers the
narrower window where the CAS succeeded but the `finalize` task was lost or its worker
died permanently. The sweep logs an event and — if a `count == F` partial exists —
enqueues `finalize`. Firing it should page us.

**Failure condition.** We revisit if any of:
1. **The backstop sweep ever fires in normal operation** → the invariant is violated
   (lost or double-consumed partial) and the guard in D3/D7 is broken. Fix the
   invariant; do not paper over it by promoting the sweep to primary.
2. **The unconsumed-partials read becomes a hot spot** — p99 of the eager-pairing
   transaction exceeds ~50 ms, or lock waits appear on the partials index → keep the
   semantic condition but maintain a *derived, transactionally-updated* `unconsumed_count`
   and `max_partial_count` on the job row as a cache, still checked against the partials
   before enqueuing `finalize`.
3. **A job legitimately has a partial with `count == F` while more work is coming** —
   i.e. F becomes mutable mid-job (streaming/appendable inputs) → `count == F` stops
   being a proof and the design must change; completion would need an explicit
   input-sealed marker.
4. **Fan-in K becomes 1 or partials become mergeable across jobs** → the partition
   argument no longer holds and the invariant must be re-derived.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Completion detection latency | `finalize` enqueued in the same transaction as the final partial commit — 0 polling delay | timestamp delta between last `reduce` commit event and `finalize` enqueue event in the `events` table |
| Conservation invariant | Σ `count` over unconsumed partials + files covered by uncommitted tasks == F, at every transaction boundary, 100% of the time | assertion in integration tests; periodic audit query in the reaper sweep |
| False completion | 0 jobs finalized with a partial whose `count != F` | DB check constraint on `finalize` task creation + result-vector spot check against a single-node reference mean |
| Backstop firings | 0 in normal operation | count of backstop-sweep events; alert on any non-zero |
| Redelivery safety | 0 duplicate result files and 0 double-consumed partials under injected redelivery | chaos test: force lease expiry on a `reduce` task mid-execution at F = 1000, verify partial `consumed_by` uniqueness and single result object |
| Multi-job isolation | each concurrent job finalizes on its own condition; no cross-job trigger | run a 25k-task job and a 3-task job concurrently, assert both complete with correct results and independent `finalize` events |
| Progress counter drift | counters may drift; correctness unaffected | inject a duplicate task completion, assert progress % is wrong-but-recovering while job still completes correctly |
