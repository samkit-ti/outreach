# Drill Deck — Anticipated Questions with Model Answers

Answer aloud in ≤30 s each. The bolded few are near-certain.

## Core mechanics

**1. Why (sum, count) and not means?** Mean-of-means is only right for equal group
sizes. F=12 splits 5+5+2: ten files of 0.0, two of 1.0 → true mean 0.1667,
mean-of-means 0.3333. Unequal groups are the *normal* case. (Σ,n) makes weighting
structural; divide by F once at the end.

**2. Why a tree at all?** A partial is C floats — file-shaped — so the 5-at-a-time
limit binds combiners identically. 20,000 partials at fan-in 5 → ⌈log₅⌉ = 7 levels.
No legal flat design exists.

**3. Why fan-in 5 and not 2?** Total reduce reads scale as k/(k−1): k=5 → ~200 GB,
k=2 → ~320 GB, plus 4× the tasks and double the depth. Largest legal k wins; the tail
uses 2–4 (drain mode) only when nothing else will ever arrive.

**4. Why isn't the tree planned at submit?** A planned tree wires each reduce to five
*named* children — one slow child stalls a branch with fifty ready partials sitting
elsewhere. Commutativity means any five partials are interchangeable, so pair
whatever's ready. That's also why reduces overlap the map phase — no barrier.

**5. How do you know a job is done? (near-certain)** Conservation proof: map turns
k files into a partial with count k; reduce sums counts; consumption is exactly-once.
Unconsumed partials always partition the F files, so one partial with count=F *is*
the completed sum. Plus one liveness read (no tasks in flight). Can't fire early,
can't be missed, immune to redelivery.

**6. Why not just count completed tasks?** The task total is dynamic — reduces are
created on the fly, so the denominator doesn't exist at submit. And at-least-once
delivery makes decrements unsafe without per-task idempotency flags, at which point
the counter is a redundant projection of task state sitting on the correctness path.

## Queue

**7. Why Postgres as the queue? (near-certain)** Pairing must atomically
{mark ≤5 partials consumed + insert their reduce}. With a broker that's a dual write:
commit-then-send strands partials (silent hang); send-then-commit double-counts
(silent wrong mean). The fix, an outbox, IS a DB queue. Load: ~25k tasks/job at
seconds each — ≪1k claims/s vs SKIP LOCKED's 1–10k/s comfort zone.

**8. When would you switch to SQS?** Written triggers: sustained >5k tasks/s,
cross-region consumers, or multi-service fan-out. Behind the QueueAdapter seam, with
a transactional outbox replacing direct enqueue.

**9. How does SKIP LOCKED claiming work under contention?** Each claimer locks a
16-row candidate window, updates one, commits. Others skip locked rows — W claimers
get W distinct tasks. Window > 1 matters: with LIMIT 1, all idle claimers compute the
same winner and W−1 get nothing.

**10. Doesn't the queue table bloat?** fillfactor + autovacuum tuning, nightly
archival of terminal jobs' rows, partial indexes. The live set stays in the tens of
thousands of rows.

## Failure model

**11. What happens when a worker dies mid-task? (near-certain)** Lease 30 s,
heartbeat 10 s, reaper 5 s → detected ≤35 s, task requeued with the fencing token
rotated. The retry writes the same bytes to the same deterministic key. Three
attempts, then the task is dead and the job fails loudly with the cause.

**12. Same task runs twice — why is the answer still exact?** Three interlocking
guards: deterministic output keys (retry overwrites itself), fenced commit
(token+status — a zombie's late commit matches zero rows), and UNIQUE(produced_by)
(the same sums can't be recorded twice).

**13. Worker wedged but heartbeating?** The heartbeat can't extend past the absolute
deadline (`lease_expires_at < deadline_at` conjunct); the reaper reclaims on
`now() > deadline_at`. Liveness never depends on a worker's self-report.

**14. Why at-least-once instead of exactly-once?** Exactly-once across a queue and
an object store doesn't exist — there's always a crash window between doing and
recording. At-least-once + idempotent effects is outcome-equivalent and buildable.

**15. What if the finalize task keeps failing?** It gets max_attempts=10 (one
idempotent 8 MB read + divide), and the reaper never fails a job that still holds a
count=F partial — it emits needs_finalize instead. A completed computation is never
discarded.

## Concurrency (deep-probe territory)

**16. Two workers commit a job's last two partials simultaneously?** Pairing is
serialised per job by pg_advisory_xact_lock. Without it, under READ COMMITTED each
could see the other's task as claimed AND undercount the partial set → both decline →
stranded forever (reachable at F=7, W=2). The lock costs milliseconds; the _xact_
variant releases on rollback too.

**17. Why READ COMMITTED?** Every guard is a conditional write — locks are taken at
write time; nothing relies on snapshot stability, so no serialization-retry handling.

**18. Who triggers pairing, exhaustively?** T2 after every successful fenced commit
(even when the partial insert was a duplicate no-op), and the reaper for every job
whose task it touches — same advisory lock. The backstop sweep is instrumentation.

## Fairness

**19. Big job running, small job arrives? (near-certain)** Claim ORDER BY
(in-flight-per-job ASC, priority, age): least-served job first → round-robin effect.
Small job finishes in ~its own work time; big job loses ~0.01%. FIFO would cost it
hours; adding workers never fixes ordering.

**20. Why finalize > reduce > map priority?** Reduce depth is the irreducible
critical path; map width is surplus parallelism. Finalize unblocks a waiting user;
draining reduces frees partial storage.

## Scale (the 10× ladder)

**21. F → 10⁶?** ~250k tasks — still fine; depth grows by one level per 5×.
**22. C → 10⁸?** A vector is 800 MB — stream column blocks *within* tasks; topology
unchanged.
**23. W → 1000?** Connection pressure first (2/worker) → PgBouncer, but transaction
pooling interacts with advisory locks — that plus claim-rate is the real SQS trigger.
**24. What breaks first at 10× overall?** Nothing in correctness; economics of the
intermediate writes (~200 GB) — first lever is task-aligned in-worker combining
(160→~32 GB at level 0).

## Extensions — the "now change the problem" round

**25. Median instead of mean? (high-probability curveball)** Median is NOT a monoid —
you can't merge two medians. The design's shape survives but the payload changes:
(a) exact: two-pass distributed selection (histogram/quantile binary search over
value ranges — O(log range) rounds of the same map/reduce machinery); (b) approximate:
mergeable sketches — t-digest/KLL *are* monoids, so partials become sketches and
everything else (queue, completion proof via count, failure model) is unchanged.
Lead with "the monoid question is the design question."

**26. Variance/std-dev?** Stays a monoid: carry (n, Σx, Σx²) — or Chan–Golub–LeVeque
combining for numerical stability. Trivial change: partial payload grows one vector.

**27. Min/max/top-k?** Min/max: trivial monoids. Top-k: bounded merge (k-way), still
associative — payload is a k-heap per index (careful: per-index top-k explodes size;
clarify the ask).

**28. Weighted FedAvg?** Partials carry (Σwᵢxᵢ, Σwᵢ); divide by total weight.
One-line change, already documented as the evolution.

**29. Files keep arriving (streaming F)?** count=F stops being a proof — F is no
longer sealed. Add an input-sealed marker per job; or shift to windowed jobs.
The honest answer: the completion proof is the thing that breaks, and I know exactly
why (it's DM-003's failure condition 3).

**30. Cancel a running job?** Designed: add 'cancelled' to job_status — the claim
query already filters on job status, so in-flight tasks drain and nothing new is
claimed. Pairing entry also checks status. One migration + one endpoint.

**31. Inputs on nodes over HTTP, not S3?** BlobStore accepts https:// with the same
allow-list; adds node-availability as a first-class failure (already an edge case)
and data-locality as a real optimization (deferred, with trigger).

**32. Multi-tenant?** Fairness ORDER BY generalises to weighted fair queuing;
admission control becomes per-tenant quotas; the allow-list becomes per-tenant.

## Implementation stories (tell them with relish)

**33. Hardest bug you dealt with?** The pairing mutual-decline race: two committers
under READ COMMITTED each undercount and both decline — job strands with no future
trigger. Found by adversarial review, closed with the per-job advisory lock, then a
second variant re-opened through ON-CONFLICT-skip + the reaper, closed by making
pairing unconditional and making the reaper a pairing trigger. There's a pinned
two-connection test that proves the serialization.

**34. What did testing catch that design didn't?** Presigned URLs signed against the
compose-internal MinIO hostname — unreachable and unverifiable from the host. Fixed
with a public-endpoint presigner (on AWS the two endpoints coincide).

**35. What would you do differently?** Bench the claim query under synthetic load
instead of modeling it; build the LISTEN/NOTIFY wake-up (the 500 ms idle poll is the
one place latency is left on the table); and wire the straggler Gantt into the
dashboard — the simulator has it, the live UI doesn't.

## Meta

**36. Why not Spark/Dask/Temporal? (near-certain)** Spark's treeAggregate is the
production answer absent the constraints — six lines. Three reasons to build: the
brief fixes the components and evaluates the orchestration algorithm itself; Spark
assumes homogeneous co-scheduled executors (withdrawn here); and the consume+enqueue
invariant fits no engine's transaction boundary.

**37. Biggest risk if this went to prod tomorrow?** No auth on a fleet-control
endpoint and modeled-not-measured throughput numbers. Both named in the docs; both
first-week fixes.
