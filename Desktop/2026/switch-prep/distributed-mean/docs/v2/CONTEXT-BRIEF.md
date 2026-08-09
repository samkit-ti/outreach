# v2 Context Brief — Locked Decisions & Canonical Vocabulary

> Single source of truth for these documents (HLD, LLD, ITDs). Every ITD must be
> consistent with this brief. If an ITD author believes a locked decision is wrong,
> flag it in the ITD's "failure condition" section — do not silently diverge.

**Version:** v2 · **Date:** 2026-08-10 · **Author:** Samkit Shah

---

## Canonical vocabulary

| Term | Meaning |
|---|---|
| **Job** | One user request: compute the index-wise mean of F files of C numbers. |
| **Task** | One unit of queued work. Types: `generate`, `map`, `reduce`, `finalize`. Many tasks per job. |
| **Partial** | An intermediate result: a vector of C partial *sums* plus a *count* n of input files it covers. Stored as an object; row in `partials` table. |
| **K** | Max fan-in = 5 (the "≤5 files at a time" RAM constraint). Applies to input files AND partials, since a partial is file-shaped (C float64s). |
| **W** | System-level worker count. Configurable via API (bonus). |
| **F, C** | Files per job (1 < F < 100k), values per file (1 < C < 1,000k). |

## Back-of-envelope (max job: F=100k, C=1M)

> The DDL bounds are exclusive, so **true maxima are F=99,999 and C=999,999**; every figure below is
> computed at the round F=10⁵ × C=10⁶ for arithmetic clarity and is therefore a ≈1‰ overestimate.

- Total input: 10¹¹ float64 ≈ 800 GB binary (~1.9 TB as CSV).
- One file / one partial vector: 8 MB binary.
- Leaf `map` tasks: ⌈F/5⌉ = 20,000. Reduce tree (fan-in 5): ≈5,000 tasks, ~7 levels.
- ≈25k compute tasks + ≈2k `generate` tasks per max job.
- A partial (8 MB) cannot ride in a queue message (SQS cap 256 KB) → queue carries references; bytes live in object store.

## Locked decisions (D1–D12)

**D1 — Aggregation topology: recursive eager 5-ary reduction through the queue.**
Workers emit partials carrying `(sum_vector, count)`. Reduce tasks combine 2–5 partials
into one. No fixed pre-built tree: reduce tasks are created *eagerly* whenever enough
unconsumed partials exist for a job (see D3). A job's final partial has count == F;
a `finalize` task divides by F and writes the result file. Rejected: two-phase barrier
map-reduce (stragglers stall the barrier), central accumulator on the API (serializes
~160 GB through one node; makes API stateful), column-partitioning (wrong axis — the
constraint is on file count, not vector width). → ITD DM-001

**D2 — Pass (sum, count), never means.** Sums are associative/commutative → combine in
any order by any worker. Mean-of-means is incorrect for unequal group sizes (F not a
multiple of 5). Divide by F exactly once, in `finalize`. → ITD DM-001, DM-010

**D3 — Adaptive fan-in ("eager pairing").** On partial commit, inside the same DB
transaction — **serialised per job by `pg_advisory_xact_lock(hashtext(job_id::text))`, with
plain `FOR UPDATE ORDER BY created_at` on partials and no `SKIP LOCKED` there (v2 hardening:
`SKIP LOCKED` let two concurrent committers each undercount the partial set and each decline to
pair, stranding partials permanently)** — if ≥5 unconsumed partials for the job → atomically
claim 5, enqueue a reduce. If the job has no other tasks pending/running and ≥2 partials remain → reduce
them (drain mode, fan-in 2–4 allowed). If exactly 1 partial remains and it has
count == F → enqueue `finalize`. Full fan-in during steady state (minimizes total
reduce work), greedy fan-in in the tail (minimizes latency; a fixed tree would let one
slow child stall a branch). → ITD DM-002

**D4 — Pull-based work distribution.** Workers claim tasks when free; nothing is ever
pushed/assigned to a specific worker. Fast workers naturally do more tasks — this plus
D3 is the primary straggler answer. Optional (documented, not in the demo): speculative
re-execution of the last in-flight tasks of a job, MapReduce/LATE-style. → ITD DM-002

**D5 — Queue = Postgres 16 `FOR UPDATE SKIP LOCKED`.** The `tasks` table *is* the
queue. Rationale: we need a DB for job/task state anyway; transactional
enqueue+state-change kills dual-write bugs (task row and queue entry commit or roll
back together — critical for D3's claim-and-enqueue transaction); leases via a
`lease_expires_at` column; fair claiming is just ORDER BY (D8). Comfortably handles
our ~25k tasks/job («1k tasks/sec). Code hides this behind a `QueueAdapter` interface;
documented switch trigger: sustained >5k tasks/sec, cross-region consumers, or
multi-service fan-out → SQS + transactional outbox. → ITD DM-004

**D6 — Data plane = S3 API everywhere.** MinIO container locally, Amazon S3 on AWS —
same code path. Queue/DB carry URIs only. Input files: CSV (one value per line,
human-readable, demo-friendly). Partials: raw little-endian float64 binary (count
lives in the `partials` row and object metadata) — 2.5× smaller than CSV, zero parse
cost. Result: CSV, mirroring input format. → ITD DM-005

**D7 — State machine + at-least-once + idempotency.** Task states:
`pending → claimed → done | failed(retryable) | dead`. Lease expiry (heartbeat-extended)
requeues tasks from crashed workers; a reaper process enforces it. All task outputs are
idempotent: deterministic object keys derived from task id, atomic PUT — a retried task
harmlessly overwrites. Consuming partials (D3) is guarded so a redelivered reduce task
cannot double-consume. Max attempts (3) → task `dead` → job `failed` with cause. → ITD DM-006

**D8 — Multi-job fairness: round-robin via claim ordering.** The SKIP LOCKED claim
query orders candidate tasks by (in-flight tasks of that job ASC, task priority, age).
Priority: `finalize` > `reduce` > `map` > `generate` (draining reduces shortens the
critical path and frees partials). Effect: a 25k-task job and a 3-task job make
concurrent progress; no starvation. Rejected: strict FIFO (starvation), weighted fair
queuing with configurable weights (over-engineering for v1, noted as evolution). → ITD DM-007

**D9 — Input generation is itself distributed.** `generate` tasks create ~50 files
each (uniform [0,1) float64, per-file deterministic seed for reproducibility).
Generating 100k files is real work and must not serialize on the API. `map` tasks for
a batch become eligible once its files exist. → covered in DM-001/DM-006 context

**D10 — Workers: Python 3.12 single-loop processes; W reconciled by a supervisor.**
Worker loop: claim → heartbeat → execute → commit (all state transitions
transactional). Workers register in a `workers` table with heartbeats (feeds UI and
liveness). W configurable: API writes `desired_workers`; a supervisor reconciles
actual→desired (docker compose scale locally; ECS service desired-count on AWS). → ITD DM-008

**D11 — Observability: event log + SSE.** Append-only `events` table; API streams
Server-Sent Events to the UI (workers free/busy, jobs queued/running/done, task
throughput, per-job progress %). SSE over WebSocket (one-way flow, auto-reconnect,
plain HTTP) and over polling (latency, chattiness) — poll fallback kept. → ITD DM-009

**D12 — Numerics: float64 + (sum,count) + tree reduction.** Values in [0,1) → max
possible sum 100k « 2⁵³, no overflow/precision cliff. The 5-ary reduction tree is a
pairwise-summation variant: the worst-case rounding bound is O(log₅F · ε) vs O(F·ε) for
*naive serial* accumulation — so the distributed design is **accuracy-neutral versus a
real single-node `numpy.mean`** (numpy already pairwise-sums internally) and ~10⁴× tighter
than a naive serial loop only. The claim is "distribution costs us nothing in accuracy",
not "distribution beats numpy" (v2 reframing). Kahan summation evaluated and rejected as
unnecessary at these bounds (documented). → ITD DM-010

## Deployment story

- **Local demo:** docker-compose — API (Node 22/Express/TS), Postgres 16, MinIO,
  W× Python workers, supervisor, UI (static + SSE).
- **AWS:** ECS Fargate (API service + worker service), RDS Postgres, S3, ALB. Same
  containers, `QueueAdapter`/`BlobStore` unchanged (Postgres queue defended at this
  scale; SQS is the documented evolution, not the default).

## Consistency rules for ITD authors

1. Follow the template in `itds/TEMPLATE.md` exactly. Status: **DECIDED**. Date: 2026-08-10. Author: Samkit Shah.
1b. **Column and endpoint names are quoted from `03-lld.md` §1/§6 — never re-invented; the LLD DDL is the single source of truth.** Canonically: `partials.produced_by` / `partials.consumed_by` (never `task_id`, `consumed_by_task_id`, `consumed_at`); `tasks.status` (never `state`); job states `pending / running / finalizing / completed / failed`; endpoints `PATCH /system/workers` and `GET /events` (SSE); event `job.submitted` (never `job.created`); priority `finalize=0 < reduce=1 < map=2 < generate=3` so the claim query sorts `priority ASC`. Constants: lease 30 s, heartbeat 10 s, reaper 5 s, worst-case detection 35 s.
2. Use the vocabulary above verbatim (job/task/partial/K/W/F/C).
3. Quote the envelope numbers from this brief — do not re-derive different ones.
4. Alternatives must be real (a reasonable person could choose them) with honest cons; the chosen section must make a positive case AND state a failure condition (what would make us revisit).
5. Cross-reference related ITDs by id (DM-001…DM-010) and the HLD (`../02-hld.md`).
6. Every claim should survive a "why not X?" probe — write nothing that cannot be defended in a follow-up discussion.
