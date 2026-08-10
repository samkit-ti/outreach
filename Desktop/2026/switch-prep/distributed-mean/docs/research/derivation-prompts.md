# Derivation Prompts — Questions to Extract Formal Depth

Paste-ready questions, each aimed at getting a chunk-sizing-grade derivation for one
part of this design. Each states our design's actual parameters so the answer lands
on our numbers. Ordered by expected value.

## Scheduling & queue

1. **Claim contention.** "W workers pull from one Postgres table with
   `FOR UPDATE SKIP LOCKED`, a fairness ORDER BY (least-in-flight job first), and a
   16-row candidate window updated to one row per claim. Task service time ~2.2 s.
   Model claim-collision probability and claim latency as functions of W and the
   window size L. Derive: at what W does claim overhead exceed 5% of worker
   wall-clock, and what is the optimal L(W)? Include the degenerate L=1 case where
   all idle claimers compute the same winner."

2. **Per-job advisory-lock ceiling.** "Every partial commit for a job serializes on
   `pg_advisory_xact_lock('pairing', job_id)`; the locked section is a SELECT FOR
   UPDATE over ≤~2KW unconsumed-partial rows plus up to a few INSERTs (measure ~1–5 ms).
   Model the throughput ceiling this imposes on one job as commit rate approaches
   1/hold-time. At F=10⁵, W=32, ~2.2 s tasks — how far from the ceiling are we, and
   what is the first safe relaxation (optimistic pairing with retry? sharded pairing
   by count-class?) with a correctness argument."

3. **Fairness sojourn time.** "Model the queue as a pull system with heterogeneous
   servers. Compare small-job sojourn time under (a) global FIFO, (b) least-in-flight-
   job-first claim ordering, (c) deficit round-robin per-job queues, as a function of
   big-job size N and W. Quantify the convoy effect FIFO produces and whether (b) and
   (c) differ measurably at J ≤ 10 concurrent jobs."

4. **Speculative-execution threshold.** "Reduces and maps are idempotent (deterministic
   output keys), so duplicating a task is safe but costs a duplicate ~40 MB read.
   Given worker-speed distribution p_i and k tasks left in flight, derive the
   expected-makespan condition under which duplicating the projected-last task wins —
   the LATE threshold specialized to this system. Where does the break-even sit for a
   fleet with one 10× straggler?"

## The reduce tree

5. **Fan-in optimality under overlap.** "Reduce fan-in is capped at k ≤ 5 (a partial
   is file-shaped; the RAM constraint binds combiners). Total reduce reads scale as
   k/(k−1), favoring k=5. But reduces are created eagerly and overlap the map phase —
   they are not a barrier phase. Build the full makespan model (map service + reduce
   availability + queueing per level) and prove or disprove that maximal k stays
   optimal under overlap, including the drain-mode tail (fan-in 2–4 when nothing else
   is in flight)."

6. **Drain-mode bound.** "Derive the expected number of sub-maximal-fan-in reduces per
   job under eager pairing with drain mode, as a function of worker-speed variance,
   and verify the claim it is bounded by tree depth (~7 at F=10⁵, <0.15% extra work).
   What speed distribution maximizes it?"

7. **In-worker combining dial.** "A worker may combine the partials of its own
   completed tasks before writing (task-aligned flush, preserving per-task retry
   idempotency). Derive the optimal flush interval as a trade between intermediate
   bandwidth saved (level-0 traffic 160 GB → 160/FLUSH GB) and expected redo work on
   crash (rate λ), and compare against the cross-task-accumulator variant that loses
   task alignment."

## Failure & time

8. **Lease-parameter optimization.** "Leases 30 s, heartbeats 10 s, reaper every 5 s,
   absolute deadline 300 s, tasks ~2.2 s, crash rate λ per worker-hour. Derive
   expected wasted work + detection latency as f(h, L, r, D) and optimize. Where does
   30/10/5/300 sit relative to the optimum, and how do the constants scale if task
   time grows 10×?"

9. **PgBouncer trap.** "Workers hold 2 Postgres connections each (execute/commit +
   heartbeat); scaling past ~100 connections suggests PgBouncer in transaction mode.
   But the pairing step relies on pg_advisory_xact_lock and session-visible state.
   Derive precisely which pooling modes preserve xact-scoped advisory-lock semantics,
   what breaks in transaction mode, and the correct scaling path to W in the hundreds."

10. **SSE gapless bound.** "Events use BIGSERIAL ids (assigned in id order, visible in
    commit order); the tail reads `WHERE id > cursor AND ts < now() − 1s`. Derive the
    exact safety condition (max in-flight transaction age vs the lag), the failure
    probability if a transaction outlives the lag, and design the exact gapless
    alternative using pg_current_snapshot()/xmin horizons with its added cost."

## Numerics & data plane

11. **Error-bound sharpening.** "F=10⁵ float64 addends per index, summed through a
    fan-in-5 tree of depth ~7. Derive both the worst-case O(depth·ε) bound and the
    probabilistic (random-walk, ~√n·ε) expected error; compare against numpy's
    pairwise blocks and Kahan. At what dynamic range between addends (model weights
    spanning orders of magnitude) does Kahan become necessary?"

12. **Weighted-FedAvg numerics.** "Partials generalize to (Σ wᵢxᵢ, Σ wᵢ) for weighted
    averaging with client sample counts as weights. Derive error and overflow bounds
    when weights span 1..10⁶, and whether pre-normalizing weights per job beats
    carrying raw sums."

13. **Object-store saturation.** "The max job reads 800 GB of inputs and moves ~400 GB
    of intermediates through jobs/{jobId}/partials/. Given S3 per-prefix request-rate
    limits and per-connection throughput, model the worker count at which the object
    store, not compute, becomes the bottleneck, and whether the single-prefix partial
    layout needs sharding."

## Architecture cross-checks

14. **Outbox inevitability.** "Prove or refute: any design where the task queue is a
    separate system from the state store either accepts a hang/double-count window on
    the commit-then-enqueue step or implements a transactional outbox (i.e. a
    DB-backed queue). Derive the minimum achievable inconsistency window for
    SQS+DynamoDB with an outbox relay, versus zero for single-DB transactional
    enqueue, and the throughput each supports."

15. **Cost-optimal W.** "Derive the AWS cost model per job as f(F, C, W): Fargate
    active-CPU seconds (~25k tasks × 2.2 s of work spread over W), RDS instance-hours,
    S3 request costs (~50k ops) and storage-days on intermediates. Then derive the
    cost-optimal W for a job with deadline T, and the marginal cost of halving
    makespan."
