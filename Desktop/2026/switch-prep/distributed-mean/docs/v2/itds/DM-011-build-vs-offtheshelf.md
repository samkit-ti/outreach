# ITD: DM-011 — Build on Primitives vs Off-the-Shelf Compute/Workflow Engines

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001 (topology), DM-003 (completion), DM-004 (queue), DM-008 (worker runtime — rejects Celery/RQ/Ray for the *worker* layer), ../02-hld.md §1, ../CONTEXT-BRIEF.md

---

## Problem Statement

Index-wise mean over F files (up to ~10⁵ files / ~800 GB) is a solved problem in every
mature data-parallel engine: Spark computes it in ~6 lines of `treeAggregate`, Dask in
a handful of `dask.array` calls, and dynamic fan-out with durable child tasks is the
canonical Temporal demo. Before designing anything, the framing question must be
answered up front: **why is this system built from primitives (API +
Postgres + object store + bare Python workers) instead of adopting an engine whose
whole job is distributed aggregation?** An unexamined "we just built it" reads as
not-invented-here; an examined decision is a strength.

---

## Context

- The brief **fixes the component list**: NodeJS/Express/TS API, a DB, a queue ("any
  kind"), and a fleet of Python workers. It also names the deliverables: the
  distribution algorithm, the split of F > 5 jobs into queue items, completion
  detection, and multi-job concurrency.
- The brief's constraints are pedagogical: K = 5 fan-in, heterogeneous worker speeds,
  "design your worker orchestration algorithm". The deliverable *is* the scheduler.
- Our design's correctness spine is one transaction (D3/DM-004): {consume ≤5 partials
  + enqueue their reducer} atomically, serialised per job by an advisory lock.
- DM-008 already rejected Celery/RQ/Ray as the *worker runtime*; this ITD answers the
  bigger version: replacing the whole architecture with an engine.

---

## Alternatives

### Adopt a data-parallel engine (Spark / Dask)

Run the job as `spark.read → treeAggregate(depth=⌈log₅F⌉) / F`, or the Dask
equivalent; the API submits applications to a cluster.

**Pros:**
- ~6 lines for the whole computation; `treeAggregate` *is* our 5-ary tree, hardened by
  a decade of production use.
- Shuffle, retries, speculative execution, and locality come free.
- The honest production answer at this problem shape if the component constraints
  vanished.

**Cons:**
- Forfeits the deliverable: the deliverable the brief names (orchestration algorithm, queue-item
  design, completion detection) disappears inside Spark's DAG scheduler — the
  submission becomes "I configured Spark".
- Violates the fixed component list (no Express/TS API in front of a queue of our
  choosing; workers are executors, not "Python workers waiting on a queue").
- Spark's driver/executor model assumes homogeneous, co-scheduled executors; the
  prompt explicitly withdraws that assumption (heterogeneous speeds is a evaluated
  scenario, handled by pull-based claiming in our design, DM-002).
- Cluster operational weight (driver HA, shuffle service, YARN/K8s) dwarfs the system
  it replaces at this scale.

### Adopt a durable workflow engine (Temporal / AWS Step Functions)

Model the job as a workflow: fan out map activities, reduce via continue-as-new or
child workflows; Temporal guarantees durable state and at-least-once activities.

**Pros:**
- Durable execution, retries, heartbeats, and task queues are first-class — much of
  DM-006 comes free.
- Dynamic fan-out (our eager tree) is expressible with child workflows.
- Strong story for long-running, audit-heavy orchestration.

**Cons:**
- The event-history model prices dynamic fan-out badly here: ~27k activities per max
  job × history events per activity, against Temporal's per-workflow history limits —
  forcing continue-as-new choreography that re-introduces exactly the coordination
  we designed away.
- The load-bearing invariant — partials consumed exactly-once *atomically with*
  reducer creation — lives in **our** DB, outside Temporal's transaction boundary; we
  would still need the Postgres transaction, now coordinated with a second stateful
  system (the dual-write DM-004 exists to kill).
- The queue stops being "any kind" — it becomes Temporal's, hiding the evaluated
  queue-item design.

### Adopt a task framework end-to-end (Celery / RQ / Ray)

Celery chords for fan-in, Redis/RabbitMQ broker, Python everywhere.

**Pros:**
- Cheap to stand up; chord = our fan-in as a library primitive.
- Ray would even give distributed shared objects for partials.

**Cons:**
- DM-003 documents why chord synchronization (counter or poll) is the weaker
  completion design for a *dynamic* task graph; DM-008 documents the worker-runtime
  rejection (opaque prefetch/acking vs our 20-line claim loop).
- Cross-language boundary (TS producer) is second-class in Celery's protocol.
- Same dual-write problem: broker enqueue vs DB state.

### Build on primitives — Postgres queue + object store + bare workers *(chosen)*

The design of this doc set: DM-001…DM-010.

**Pros:**
- The deliverables the brief names are all visible and ours: split policy, eager tree, completion
  proof, fairness — each a decision record, not a config flag.
- One transactional substrate: the consume-and-enqueue invariant is a single Postgres
  transaction — no engine offers this across its boundary.
- Component list matches the brief exactly.
- Total moving parts: 5 containers; smaller than any engine's control plane.

**Cons:**
- We own retries, leases, fencing, fairness — ~every failure mode DM-006 enumerates
  is our code — and the lease/pairing layer is exactly where the subtle bugs live
  (fencing, token rotation, pairing races); engine users never meet them.
- No speculative execution, locality, or shuffle optimizations unless we build them
  (DM-002 defers speculation deliberately).
- At true production scale/generality (arbitrary DAGs, many job types), this converges
  toward re-implementing an engine — the classic trap.

---

## Chosen: Build on primitives, and say why out loud

**The decision.** Build the system from the brief's own primitives. State in the HLD
(§1) that Spark `treeAggregate` is the production answer *absent these constraints* —
the rejection is context-bound, not ideological.

**Positive case.** The brief evaluates the orchestration algorithm itself; the fixed
component list is the brief drawing the system's boundary for us. Within that
boundary, the strongest possible design is one where the correctness spine —
consume-partials + enqueue-reducer, atomically, per job — lives in a single
transactional store, which is precisely the thing no engine exposes across its API.
Everything distinctive in this submission (the eager 5-ary tree, the `count == F`
proof, fairness as an ORDER BY) exists *because* we own that transaction.

**Why each rejection.** *Spark/Dask*: right tool, wrong constraints — it erases the deliverable
itself, breaks the fixed component list, and its executor model assumes away the
heterogeneity the brief makes central. *Temporal*: dynamic fan-out at 27k
activities/job fights its history model, and the exactly-once partial-consumption
invariant would still need our Postgres transaction — two stateful systems where one
suffices. *Celery/Ray*: inherits DM-003's counter-vs-proof analysis and DM-008's
worker-runtime rejection; adds a cross-language second-class citizen and the broker
dual-write.

**Failure condition.** Revisit if: (1) the component constraints are lifted and the
task becomes "compute this at production scale" → adopt Spark `treeAggregate` and
delete most of this repo; (2) job types multiply beyond this one aggregation shape
(arbitrary DAGs, human-in-the-loop steps) → a workflow engine earns its operational
cost; (3) the team inherits an existing Spark/Temporal platform → marginal cost of
adoption drops below the cost of owning DM-006's failure matrix.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| The framing question lands pre-empted | "Why not Spark?" is answered in the HLD opening section | present in 02-hld.md |
| Owned-complexity honesty | The cost of building — owning fencing, token rotation, and pairing races — is stated, not hidden | CHANGELOG referenced in this ITD |
| Boundary discipline | No second stateful coordination system appears in the design | component inventory in HLD §2 |
