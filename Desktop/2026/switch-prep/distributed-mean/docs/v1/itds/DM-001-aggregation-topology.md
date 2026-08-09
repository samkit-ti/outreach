# ITD: DM-001 — Aggregation Topology

**Date:** 2026-08-09
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-002 (adaptive fan-in / stragglers), DM-004 (queue), DM-005 (storage & formats), DM-006 (idempotency), DM-010 (numerical correctness), ../02-hld.md, ../CONTEXT-BRIEF.md
**Simulation:** [Design Lab — Topology tab](https://claude.ai/code/artifact/ee9896b4-7e99-4aeb-b378-33290d2acd41) — race the eager tree against the barrier, fixed tree, and central accumulator.

---

## Problem Statement

A **job** must compute the index-wise mean of **F** files × **C** numbers, where a single
**worker** may hold at most **K = 5** files at a time. At the envelope maximum (F = 100k,
C = 1M) the input is 10¹¹ float64 ≈ **800 GB binary (~1.9 TB as CSV)**, and one file — or one
**partial** — is **8 MB**. No single worker can see the job, so the job's output must be
assembled from ≥ ⌈F/5⌉ = **20,000** independent worker outputs. This ITD decides *how those
20,000 outputs are combined into one result file*: the shape of the aggregation, what an
intermediate result carries on the wire, and where the division by F happens. The decision
must (a) never produce a wrong mean, (b) never route the whole job through one process, and
(c) give a completion test the system can evaluate without trusting a task counter.

---

## Context

Constraints that bind this decision:

- **K = 5 is a fan-in limit, not a file-reading limit.** A partial is a vector of C float64s —
  **exactly the same shape and size as an input file (8 MB)**. So a reduce step that combines
  partials is subject to the same ≤5 constraint as a map step over files. This single
  observation is what makes aggregation *recursive*: combining 20,000 partials 5-at-a-time
  needs ⌈log₅ 20,000⌉ = **7 levels** and **≈5,000 reduce tasks**. Total: **≈25k compute tasks
  + ≈2k `generate` tasks per max job** (D9 — input generation is itself distributed).
- **Workers process files at different speeds** (given in the prompt). Any structure with a
  synchronisation point converts the slowest worker into the job's clock.
- **Multiple jobs run concurrently** (graded aspect #4), so no per-job singleton process may
  hold job state in memory.
- **The queue cannot carry data.** An 8 MB partial does not fit an SQS message (256 KB cap),
  so the queue carries references and bytes live in the object store (D5, D6 → DM-004, DM-005).
- **"How the system decides a job is finished" is explicitly graded** (aspect #3). A topology
  that makes completion a property of the *data* is worth more than one that makes it a
  property of a bookkeeping counter.
- F is user-chosen and **not** guaranteed to be a multiple of 5. F = 12 is a legal job.

---

## Alternatives

### Recursive eager 5-ary reduction through the queue *(chosen)*

`map` tasks each read ≤5 input files and emit one partial `(sum_vector, count)`. `reduce`
tasks each read 2–5 partials and emit one partial whose `sum` is the element-wise sum and
whose `count` is the sum of the input counts. Reduce tasks are created **eagerly** whenever
enough unconsumed partials exist for the job (D3 → DM-002) — there is no pre-built tree. When
one partial remains and its `count == F`, a `finalize` task divides by F and writes the result
CSV.

**Pros:**
- Sum is associative and commutative, so *any* worker may combine *any* partials in *any*
  order — the scheduler is free, which is exactly what heterogeneous worker speeds demand.
- No barrier: `map` and `reduce` work overlap, so a worker that finishes early picks up reduce
  work on already-complete partials instead of idling.
- Bounded storage high-water mark. Eager consumption keeps live unconsumed partials at
  O(W·K), not the 20,000 × 8 MB = **160 GB** that accumulates if reduction is deferred.
- Completion is a data property: `count == F` on the last remaining partial. Cheap, and robust
  to at-least-once redelivery (DM-006) in a way that "20,000 map rows are `done`" is not.
- Critical path is 7 reduce levels regardless of W — depth grows logarithmically in F, so
  raising the F cap 5× adds one level.

**Cons:**
- Writes ~200 GB of intermediate partials at the max job (160 GB at level 0, then 32 GB,
  6.4 GB, …) — pure overhead relative to the 800 GB of input reads.
- Requires a transactional claim-and-enqueue (D3) so two concurrent partial commits cannot
  consume the same partial twice; that is real concurrency-control work.
- Tree shape is nondeterministic run-to-run, so results are reproducible to ~1e-15 but not
  bit-identical (DM-010); and per-job progress % is estimated, not exact, because the reduce
  task count is unknown at submit time.

### Two-phase map-then-reduce with a barrier

Run all ⌈F/5⌉ = 20,000 `map` tasks. When the last one completes, start the reduce phase over
the resulting 20,000 partials.

**Pros:**
- Simplest possible reasoning: two phases, one boundary, exact progress % in each phase.
- The reduce phase can be planned optimally because the exact partial count is known.
- No eager-pairing transaction; a plain "count of done map tasks == 20,000" gate.
- Naturally batches: the object store sees one read-heavy phase then one write-heavy phase.

**Cons:**
- The barrier makes the **slowest single map task** the start gate for *all* reduce work. With
  heterogeneous workers that is precisely the failure the prompt asks us to design around.
- Workers idle at the boundary — the fast ones have nothing to claim while the tail finishes.
- Peak intermediate storage is the full **160 GB** of level-0 partials, all resident
  simultaneously; eager reduction never materialises that set.
- **It does not even buy structural simplicity.** Because a partial is file-shaped, the reduce
  phase *still* needs a recursive 5-ary tree — 20,000 partials cannot be reduced in one step.
  So this is the chosen topology *plus* a barrier, not a simpler topology.

### Central streaming accumulator on the API / aggregator node

One process holds a single C-length float64 accumulator (`sum_vector`) plus a counter. Workers
(or the API itself) stream partials into it; when the counter reaches F it divides and writes.

**Pros:**
- **Memory is genuinely not the objection** — the accumulator is O(C) = **8 MB**, and even 100
  concurrent jobs is 800 MB. This alternative is *feasible*, which is why it deserves a
  straight answer rather than a hand-wave.
- Zero intermediate partial writes beyond level 0 — no 200 GB of reduce traffic, no reduce
  tasks at all, no reduce tree, no eager-pairing transaction.
- Trivially exact completion (`count == F`) and trivially exact progress %.
- Deterministic if ingestion order is fixed.

**Cons:**
- **Bandwidth is the objection.** All 20,000 level-0 partials (**160 GB**) must traverse one
  node's NIC. At 1 Gbps that is ~21 minutes of pure wire time with zero compute; at 10 Gbps
  ~2 minutes. Worse, it is a *serial floor*: adding workers cannot reduce it (Amdahl), so the
  system stops scaling exactly where the exercise starts getting interesting.
- **It makes the API stateful.** The accumulator lives in process memory, so an API restart
  mid-job loses it unless it is checkpointed — and a checkpointed per-job accumulator vector
  *is* the `partials` store, re-invented with worse ergonomics. It also breaks the deployment
  story (D: ECS API service behind an ALB, ≥2 tasks): correct routing would need per-job
  sticky sessions or a leader election.
- **It violates the spirit of the K = 5 constraint.** The letter is satisfied (the node holds
  one vector and streams). But "≤5 files at a time" is a stand-in for "you may not assume one
  node can see the whole job", and this design re-introduces the single-node bottleneck the
  constraint exists to teach you to design around. This is a judgement call about what is
  being graded, and I would state it as such in the interview rather than pretend the
  engineering alone kills it.

### Column-range sharding of the C dimension

Instead of (or in addition to) splitting on F, split on C: task *j* handles columns
[j·C/S, (j+1)·C/S) across files.

**Pros:**
- Bounds per-task memory independently of C — the right tool if C, not F, were the binding
  dimension.
- Produces many small uniform tasks, which is good for load balance and tail latency.
- Enables parallel result writes (each shard writes its own byte range of the output).
- A legitimate **second axis** if C grew far beyond the current 1M cap.

**Cons:**
- **Wrong axis for the stated constraint.** The RAM limit is expressed in *files*, so a
  column-sharded task still may not open more than 5 files. Sharding C reduces fan-in by
  exactly zero and the F-dimension tree is still required — this is additive work, not a
  replacement.
- Multiplies task count by S (20,000 × S) without removing a single reduce level.
- **S× read amplification.** Input is line-oriented CSV (D6), so reaching a column range means
  scanning the file to that line; each of the F files is re-read once per shard, turning
  800 GB of reads into S × 800 GB.
- `finalize` must stitch S shards into one ordered result file, adding a join step.
- At the current envelope it buys nothing: a full C = 1M vector is 8 MB, which is not a memory
  problem for any plausible worker.

### Pre-planned static reduction tree

Insert the whole task DAG (20,000 map + ≈5,000 reduce + 1 finalize rows) at submit time with
explicit parent/child dependencies; each reduce becomes eligible when its 5 named children are
done.

**Pros:**
- Exact progress % and an exact critical path, known before any work starts.
- Deterministic tree shape → bit-reproducible results across runs (see DM-010).
- No claim-and-enqueue transaction; eligibility is a plain dependency check.

**Cons:**
- **One slow child stalls its branch and every ancestor of that branch.** A fixed tree cannot
  reassign a straggler's slot to an idle worker, which reintroduces the barrier problem at
  every internal node instead of once globally.
- Cannot exploit early-finishing siblings: five ready partials belonging to different planned
  groups must still wait for their planned peers. Tail groups (F % 5 ≠ 0) are likewise fixed at
  plan time, so the tail is as slow as planned rather than as slow as observed.
- ~25k rows written up front per job, before we know the job will not be cancelled.

*(The eager-vs-static comparison is the substance of D3 and is argued in full in DM-002; it is
listed here because it is a genuine topology alternative, not only a scheduling one.)*

---

## Chosen: Recursive eager 5-ary reduction through the queue, on `(sum, count)` partials

**The decision.** `map` tasks read ≤5 input files and emit a partial carrying
`(sum_vector, count)`. `reduce` tasks read 2–5 partials and emit one partial with the
element-wise sum and the summed count. Reduce tasks are enqueued eagerly as soon as enough
unconsumed partials exist (D3 → DM-002). Division happens **exactly once**, in `finalize`,
when a single partial with `count == F` remains. At F = 100k, C = 1M this is **20,000 leaf
`map` tasks, ≈5,000 `reduce` tasks across ~7 levels**, plus ≈2k `generate` tasks and one
`finalize`.

**Positive case — three properties, not just the absence of problems:**

1. **Sums are a monoid; means are not.** `(sum, count)` pairs combine associatively and
   commutatively, which is what lets *any* free worker combine *any* two partials the instant
   both exist. That algebraic freedom is the scheduling freedom the prompt's "workers process
   files at different speeds" requirement needs — the topology and the straggler answer are
   the same design, not two.

2. **Passing means instead is not a style choice, it is a correctness bug.** With F = 12 and
   K = 5 the groups are 5, 5, 2. Take ten files of 0.0 and two files of 1.0 at some index. The
   true mean is 2/12 = **0.1667**. Mean-of-means gives (0 + 0 + 1)/3 = **0.3333** — off by 2×,
   with no error, no exception, and a plausible-looking output file. And under D3's adaptive
   fan-in, groups of size 2–4 occur in drain mode *even when F is a multiple of 5*, so unequal
   group sizes are the **normal** case, not an edge case. `(sum, count)` makes the weighting
   structural: the arithmetic cannot be wrong regardless of how the tree came out.

3. **A partial is file-shaped, so recursion is forced and completion becomes free.** Because a
   partial is C float64s = 8 MB — the same shape as an input file — K = 5 applies to reduces
   too. Reduction is therefore recursive with ⌈log₅⌉ depth: 7 levels over 20,000 partials, and
   the critical path grows logarithmically (a 5× larger F cap costs one more level). The
   `count` field then doubles as the completion test: *one partial exists and its count == F*.
   That answers graded aspect #3 from the data rather than from a task ledger, which matters
   because at-least-once delivery (D7) makes "all 20,000 map rows are done" a claim about
   bookkeeping while `count == F` is a claim about the numbers themselves. `count` is an
   integer, so the check is exact — no float comparison (DM-010).

**Why each alternative was rejected, specifically:**

- **Two-phase barrier:** the slowest of 20,000 map tasks would gate every reduce task, and
  peak intermediate storage would be the full 160 GB instead of O(W·K) partials. It also
  fails to simplify anything — because a partial is file-shaped, it needs the identical 5-ary
  tree in phase 2, so its only net contribution is the barrier.
- **Central accumulator:** rejected on **bandwidth, not memory** — the 8 MB accumulator is
  fine; forcing 160 GB through a single NIC (~21 min at 1 Gbps) is a serial floor that adding
  workers cannot lower. Secondarily it makes the API stateful (breaking restart-safety and
  multi-instance deployment behind an ALB), and it satisfies the letter of the 5-file
  constraint while defeating its purpose.
- **Column sharding:** rejected as the wrong axis — the constraint counts files, not vector
  width, so sharding C reduces fan-in by zero while multiplying task count by S and
  re-reading every CSV once per shard. Retained explicitly as the evolution path if C, not F,
  becomes binding.
- **Pre-planned static tree:** rejected because a fixed parent/child wiring cannot hand a
  straggler's slot to an idle worker; it converts one global barrier into a barrier at every
  internal node. Its one real advantage — a deterministic tree shape — is preserved as an
  opt-in escape hatch (see DM-010's reproducibility failure condition).

**Failure condition.** Revisit this decision if any of the following is observed or specified:

1. **Intermediate partial I/O dominates.** If measured `reduce`-level partial read+write bytes
   exceed **40% of job wall-clock time**, add in-worker combining: a worker that has just
   produced K partials reduces them locally before writing, collapsing a level and cutting
   level-0 traffic from 160 GB toward 32 GB.
2. **C cap raised such that one partial exceeds a worker's RAM budget** (roughly C > 10⁸ →
   800 MB/vector). Then column-range sharding is added as a *second* axis, as described above.
3. **F cap dropped to ≤ 25.** The tree collapses to ≤2 levels and a single planned reduce is
   simpler than eager pairing; the machinery stops paying for itself.
4. **Bit-identical output across runs becomes a requirement.** Eager pairing yields a
   nondeterministic tree shape; satisfying that requirement means pinning the tree (canonical
   ordering by partial id, drain mode disabled) or moving to exact accumulation — both are
   scoped in DM-010.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Correctness with unequal groups | F = 12 fixture (ten 0.0 files, two 1.0 files), max abs error vs single-node numpy oracle ≤ 1e-15 | Integration test asserting against `numpy.mean(axis=0)` |
| No mean-of-means regression | The same F = 12 fixture fails loudly (≥0.16 error) if a partial ever carries a mean | Design-guard / negative test on the partial schema |
| Task-graph shape at max job | F = 100k, C = 1M → 20,000 `map`, ≈5,000 `reduce`, 7 levels, ≈2k `generate`, 1 `finalize` | `SELECT type, count(*) FROM tasks GROUP BY type`; level from reduce depth column |
| Map/reduce overlap (no barrier) | First `reduce` task claimed strictly before the last `map` task completes | `events` table timestamps (D11) |
| Bounded intermediate storage | Peak unconsumed partials per job ≤ 5·W + 5 (never the 20,000-partial / 160 GB set) | Sampled `SELECT count(*) FROM partials WHERE consumed_by IS NULL` |
| No single-node bottleneck | No host carries > 5% of total partial bytes for a job | Per-worker byte counters in the `events` stream |
| Completion is data-derived | 100% of job completions triggered by `count == F` on the sole remaining partial; zero completions triggered by a task-count heuristic | Code path assertion + `events` audit |
| Critical path scales as log₅F | Reduce levels: F=10³→5, F=10⁴→6, F=10⁵→7 | Level counts across three scale runs |
