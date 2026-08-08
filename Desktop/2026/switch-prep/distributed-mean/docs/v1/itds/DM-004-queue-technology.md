# ITD: DM-004 — Queue Technology

**Date:** 2026-08-09
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001, DM-002, DM-003, DM-006, DM-007, ../02-hld.md, ../CONTEXT-BRIEF.md

---

## Problem Statement

The system needs a work queue that a **NodeJS/Express/TypeScript API** writes to and a fleet of **W Python
workers** reads from, carrying up to **≈25k compute tasks + ≈2k `generate` tasks** for a single max-size job
(F=100k, C=1M) — ≈27k tasks per job, with multiple jobs in flight concurrently. The queue must support: (a)
an **atomic claim-and-enqueue** in the eager-pairing step of D3, where marking ≤5 partials consumed and
creating the resulting `reduce` task must either both happen or neither happen; (b) **leases** so a task
claimed by a worker that crashes or hangs returns to `pending` (D7); (c) **claim ordering by mutable global
state** — "prefer the job with the fewest in-flight tasks, then by task priority `finalize` > `reduce` >
`map` > `generate`, then by age" (D8). We must pick one queue technology, name the honest breaking point,
and put it behind an interface so the breaking point is a config change rather than a rewrite.

---

## Context

- The prompt fixes the components: **API in Node/Express/TS, workers in Python, a DB, and "Queue: any kind
  (SQS, something local, anything)."** So the queue is genuinely open — but it is **cross-language by
  construction**: the producer is TypeScript and the consumer is Python. Any queue whose semantics live in a
  single-language library is disqualified before the trade-off table starts. That removes **BullMQ /
  Bee-Queue** (Node-only; the `bullmq` Python port trails the JS reference implementation and its Lua-script
  protocol is the real contract) and **Celery** (Python-only; Node can only enqueue by hand-reimplementing
  Celery's message protocol). Both would put us in the business of maintaining a second, undocumented
  implementation of somebody else's wire format. Excluded upfront, not compared below.
- **A DB is required regardless.** We need durable job/task/partial/worker/event state for D7 (state
  machine), D8 (fairness ordering), D10 (worker registry) and D11 (event log + SSE). The question is
  therefore not "DB or queue" — it is "do we add a *second* stateful system next to a DB we already have."
- **Envelope (from CONTEXT-BRIEF):** ≈20,000 leaf `map` tasks, ≈5,000 `reduce` tasks over ~7 levels, ≈2k
  `generate` tasks. One partial is **8 MB** binary and cannot ride in a queue message (**SQS cap 256 KB**) →
  the queue carries **references only** in every alternative below. Message-size and raw broker-throughput
  arguments are therefore nearly irrelevant: our messages are a few hundred bytes of ids and URIs (see
  DM-005).
- **Task service time is I/O-bound seconds, not microseconds.** A `map` task reads 5 × 8 MB and sums; a
  `reduce` task reads ≤5 × 8 MB and sums — tens of MB of object-store traffic per task, so a worker
  completes on the order of **0.2–2 tasks/sec**. Claim rate is bounded by `W × per-task rate`, not by the
  queue.
- **Interaction with D3 is the crux.** Eager pairing runs *on partial commit* and must do three writes as
  one unit: insert/update the `partials` row, mark ≤5 partials `consumed`, insert a `reduce` task. If the
  queue is a different system from the DB, that is a **dual write** with no shared transaction.

---

## Alternatives

### Postgres 16 as the queue (`SELECT … FOR UPDATE SKIP LOCKED`) — the `tasks` table *is* the queue

The claim is a single statement: select the top-N eligible `pending` rows under the D8 ordering, `SKIP
LOCKED` so concurrent workers never block each other on the same row, `UPDATE` them to `claimed` with
`lease_expires_at = now() + interval`, `RETURNING` the payload. Heartbeats extend the lease; a reaper resets
rows whose lease expired.

**Pros:**
- **Transactional enqueue.** D3's claim-and-enqueue is one `BEGIN … COMMIT`. There is no window in which
  partials are marked consumed but the `reduce` task does not exist.
- **Ordering is a `SELECT`.** D8's "fewest in-flight tasks for that job, then priority, then age" is an
  `ORDER BY` over a join. Any selection policy expressible in SQL is available; no broker feature required.
- **Leases are a column we control** (`lease_expires_at`): timeout per task type, heartbeat-extended,
  remaining lease visible in a query. Crashed *and hung* workers covered by the same mechanism.
- **The queue is queryable.** `SELECT state, count(*) FROM tasks WHERE job_id = $1` is an exact answer —
  precisely what the D11 UI needs (jobs queued/running/done, per-job progress %). Brokers expose approximate
  depth at best.
- **One stateful system**: one backup/restore, one connection story, one container locally and one managed
  service (RDS) on AWS. Well-trodden pattern with published throughput characterisation (see Chosen).

**Cons:**
- **Churn on a hot table.** Every task row is inserted, updated ≥2× (claim, complete) and heartbeat-updated;
  ~27k tasks/job of `UPDATE`s create dead tuples and autovacuum work. Needs a fillfactor/autovacuum-tuned
  `tasks` table plus archival of finished jobs.
- **Connections don't scale like a broker's.** Each worker holds a Postgres connection; past a few hundred
  workers we need PgBouncer. SQS has no connection concept.
- **We own the machinery**: reaper, lease expiry, attempt counting, and the `dead` state that stands in for
  a dead-letter queue — ~200 lines to write and chaos-test instead of a managed feature to configure.
- **Polling.** Idle workers poll (short interval, optional `LISTEN/NOTIFY` to cut latency); SQS long-poll is
  a cleaner idle story.
- The queue shares IOPS and failure domain with the system of record: a queue overload degrades the API's
  own reads.

### Amazon SQS (LocalStack for the local demo)

Standard queues, one per task type (or one queue plus a type field). Producer: `@aws-sdk/client-sqs` from
the API. Consumer: `boto3` long-poll `ReceiveMessage`, visibility timeout as the lease,
`ChangeMessageVisibility` as the heartbeat, `DeleteMessage` on success, redrive policy → DLQ after
`maxReceiveCount`.

**Pros:**
- **Fully managed.** No vacuum, no reaper, no lease code, no capacity planning, no backup. Availability and
  durability are AWS's problem, and the operational surface handed to a future on-call is dramatically
  smaller.
- **Effectively infinite scale** for standard queues — 27k tasks/job is not a number SQS notices, and it
  would still not notice at 100× that.
- **Dead-letter queues are built in**, with `maxReceiveCount` and redrive back to the main queue. Our D7
  `dead` state is a hand-rolled version of this.
- Visibility timeout is a genuine lease equivalent, extensible per message; 14-day retention, IAM-scoped
  access, cross-account and cross-region consumers for free.
- **Cost is a non-issue**: at ~3 API calls per task, a max job is ~80k requests ≈ **$0.03** at $0.40/M.
  Rejecting SQS on price would be dishonest, so we don't.

**Cons:**
- **The dual write.** D3's eager pairing becomes {commit partial-consumption in Postgres} + {`SendMessage`
  to SQS} with no shared transaction. **Commit-then-send** loses the `reduce` task if the process dies in
  between — 5 partials marked consumed with nothing to consume them, so the job **stalls forever with no
  error**. **Send-then-commit** produces `reduce` tasks for partials never marked consumed, i.e.
  double-counted sums — a **silently wrong answer**, worse. The correct fix is a **transactional outbox**:
  write the message to an outbox table in the same transaction, then a relay polls and publishes. That relay
  needs its own claim mechanism, ordering and retry — we build most of a Postgres queue *and then also run
  SQS*.
- **No control over ordering.** Standard queues are best-effort FIFO with no priority, and D8's ordering key
  depends on *global mutable state at claim time* ("how many tasks of this job are in flight right now") —
  no broker can evaluate that. Approximating it needs one queue per job (job count is unbounded) or
  per-priority queues plus client-side weighted polling, i.e. a scheduler in the worker that reads Postgres
  anyway to decide which queue to poll.
- **SQS FIFO doesn't help.** Message groups give strict order *within* a group and no cross-group priority,
  and FIFO adds throughput limits (300 API calls/sec/queue, 3,000 batched). Strict order isn't what we want;
  reordering by in-flight count is, and FIFO cannot express it.
- **256 KB message cap** — fine given we carry URIs (DM-005), but it hard-forbids ever putting an 8 MB
  partial in a message, so the object store becomes mandatory rather than a choice.
- At-least-once with occasional duplicate delivery — acceptable since D7 makes tasks idempotent, but the
  duplicate-suppression work exists either way.
- **Queue contents are opaque.** `ApproximateNumberOfMessages` is approximate and eventually consistent, so
  the D11 UI needs the DB as the real progress source — the DB ends up mirroring queue state anyway.
- **Local demo needs LocalStack** — an extra container whose emulation is close but not identical
  (visibility-timeout timing, error shapes), so "works locally" stops implying "works on AWS."

### RabbitMQ

Durable queues with publisher confirms; consumers use `pika` (Python) / `amqplib` (Node), `basic.qos`
prefetch for load spreading, `basic.ack` / `basic.nack(requeue)` for completion, `x-max-priority` for
task-type priority, DLX for dead letters.

**Pros:**
- Real broker semantics: per-message ack/nack/reject-with-requeue, prefetch as a natural back-pressure knob,
  dead-letter exchanges, publisher confirms.
- Priority queues can encode `finalize > reduce > map > generate` directly.
- Mature, well-documented clients on **both** required languages, and the management UI gives queue depth
  and consumer state for free (part of what D11 needs). Routing/topics would let us fan the same event to
  workers and a future notifier without changing producers.

**Cons:**
- **Same dual write as SQS**, same two bad failure modes, same outbox as the only correct fix.
- **No timer-based lease.** RabbitMQ redelivers when a channel/connection *drops*, not when a deadline
  passes. A worker that is alive-but-wedged (slow S3 GET, GC pause, deadlock) holds its message with no
  expiry; `consumer_timeout` kills the *channel* and is a broker-wide setting, not a per-task lease. D4/D7
  want "reclaim after N seconds unless heartbeated" — that is `lease_expires_at` in a column, not an AMQP
  feature.
- Priority is a small integer, so it cannot express D8's fairness key (fewest in-flight tasks per job): the
  interesting half of the ordering is still unavailable. Priority also interacts subtly with prefetch — a
  consumer with prefetch>1 holds low-priority messages that arrived first, so priority is honoured at
  delivery, not at execution.
- **Another stateful service** to run, cluster (quorum queues), monitor and back up — the operational cost
  SQS explicitly avoids, without SQS's managed upside.

### Redis — Streams (consumer groups) or `BRPOPLPUSH` reliable-queue lists

Streams: `XADD` to produce, `XREADGROUP` to claim, `XACK` to complete, `XAUTOCLAIM` / `XPENDING` to reclaim
messages idle longer than N ms. Lists: `BRPOPLPUSH main processing` with a reaper over the processing list.

**Pros:**
- **Fastest option by an order of magnitude** (100k+ ops/sec on one node) — the queue would never be the
  bottleneck under any envelope we can imagine here.
- **Streams' `XAUTOCLAIM` on idle time is the closest external analogue to our lease column** — a real,
  timer-based reclaim, exactly what RabbitMQ lacks.
- First-class clients both sides (`ioredis`, `redis-py`); trivial single container locally. We may want
  Redis anyway (SSE fan-out across API replicas, caching), so it could be infrastructure we already pay for.

**Cons:**
- **Same dual write**, same outbox requirement.
- **Durability is the disqualifier.** With default persistence an acknowledged write can be lost on failover
  (AOF `everysec`, async replication). For a cache that's a re-fetch; for *this* queue a lost `reduce` task
  means partials marked consumed in Postgres with no consumer — a job that hangs forever. Making Redis
  durable enough (AOF `always` + `WAIT`) surrenders the speed that was the whole argument.
- **Lists have no lease at all.** `BRPOPLPUSH` needs a separate reaper scanning the processing list with
  per-item timestamps — reimplementing `lease_expires_at` against a weaker store. Streams instead add
  pending-entries-list bookkeeping (consumer names, `XACK` hygiene, `XTRIM`/`MAXLEN`) and still have **no
  DLQ**.
- **D8's fairness ordering is still impossible.** Streams and lists are FIFO; a sorted-set priority queue
  would mean writing our scheduler as a Lua script, duplicating in-flight counts that live in Postgres,
  against a store with weaker durability than the DB holding the truth.

---

## Chosen: Postgres 16 `FOR UPDATE SKIP LOCKED`, behind a `QueueAdapter` interface

**Decision.** The `tasks` table *is* the queue. Workers claim with a single `SELECT … FOR UPDATE SKIP
LOCKED` + `UPDATE … RETURNING` statement; leases live in `lease_expires_at` and are heartbeat-extended; a
reaper requeues expired leases; the D8 ordering is the `ORDER BY` of the claim query. All queue access in
both languages goes through a narrow `QueueAdapter` (`enqueue(tasks, tx)`, `claim(workerId, n)`,
`heartbeat(taskIds)`, `complete(taskId, tx)`, `fail(taskId, reason)`), so SQS is a new implementation of an
existing interface rather than a redesign.

**Positive case — the decisive argument is transactional enqueue.** D3 (eager pairing) is not a "publish an
event" step; it is a **state transition that includes a publish**: mark ≤5 partials `consumed` *and* create
the `reduce` task that owns them. With Postgres as the queue this is one transaction, and the invariant
"every consumed partial is owned by exactly one live reduce task" is enforced by the database. With any
external broker the step spans two systems and no ordering of the two writes is safe: commit-then-send
strands 5 partials and hangs the job forever; send-then-commit double-consumes partials and produces a
**silently wrong mean**. The industry answer — transactional outbox — is correct, and it means writing
messages to a Postgres table and polling it with a claim query. That *is* a Postgres queue. We would build
it **and** operate a broker beside it. Choosing Postgres is choosing to keep the outbox and delete the
broker.

Note the shape of the interface: `enqueue(tasks, tx)` **takes a transaction handle**. That parameter is the
whole argument in one line — a Postgres adapter honours it; an SQS adapter can only honour it via an outbox.

Two further positive properties, not just eliminations. **D8's fairness ordering is a sort key, not a
feature request**: ordering by (in-flight tasks of that job ASC, priority, age) requires evaluating mutable
global state at claim time, which SQL does natively and no broker exposes. And the queue is
**introspectable** — exact per-state counts for the D11 UI plus the ability to answer "why is this job
stuck" in one query, worth a lot in a system whose interesting failures are stalls rather than crashes.

**Throughput honesty.** A Postgres `SKIP LOCKED` queue is commonly characterised as good for roughly
**1k–10k tasks/sec**, with practitioner reports pushing a single well-tuned instance considerably further
before a broker is warranted (<https://www.dbpro.app/blog/postgresql-skip-locked>,
<https://medium.com/@harsh.vaghela.work/postgres-is-the-only-queue-you-need-until-50k-jobs-sec-5931611b551c>).
Our numbers sit far below that floor: a max job is **≈27k tasks in total**, not per second, and each task is
**I/O-bound seconds** (reading up to 5 × 8 MB from the object store). A worker finishes ~0.2–2 tasks/sec, so
even **hundreds of workers claim well under 1k tasks/sec** — one to two orders of magnitude inside the
comfortable range, with claim batching (`n>1` per claim) as further headroom. We are not choosing Postgres
because we think it is faster than SQS; we are choosing it because at *our* rate the throughput difference
is unobservable while the transactional difference is decisive.

**Why each alternative was rejected, specifically.**
- **Amazon SQS** — rejected on the dual write, not on capability or cost. It is genuinely the better
  operational choice at scale (managed, unbounded, DLQ built in, ~$0.03 per max job) and it is our
  documented evolution path. But it cannot participate in D3's transaction; it cannot express D8's claim
  ordering (standard = no priority; FIFO = strict order plus 300 calls/sec/queue and still no cross-group
  priority); it gives approximate depth where the UI needs exact; and it forces LocalStack into the local
  demo, weakening the "same code path everywhere" property we do preserve on the data plane (DM-005).
  Adopting it *correctly* means outbox + relay — strictly more machinery than what we chose.
- **RabbitMQ** — dual write, plus the specific defect that redelivery is connection-driven, not
  deadline-driven: a hung-but-connected worker holds a task indefinitely, breaking the straggler/crash
  guarantee D7's lease provides. Its integer priority still cannot express D8's fairness key. We would take
  on a clustered stateful service and get neither SQS's managed upside nor Postgres's transactional one.
- **Redis** — dual write, plus durability semantics that turn a lost message into a permanently stalled job.
  Streams' `XAUTOCLAIM` is a real lease and this option's honest high point, but configuring Redis to be
  durable enough erases the performance advantage that motivated it — and we don't need the performance.
- **BullMQ / Celery-class libraries** — excluded before comparison: single-language semantics against a hard
  cross-language requirement (TS producer, Python consumer).

**Failure condition — what would make us revisit.** Move to **SQS plus a transactional outbox** when any one
of these holds: (1) **sustained claim rate above ~5k tasks/sec** measured on the `tasks` table — approaching
the documented Postgres queue band, and the point where vacuum/connection pressure competes with the API's
own reads; (2) **cross-region consumers** — workers outside the DB's region, where per-claim round-trip
latency and connection fragility make polling a remote Postgres untenable; (3) **multi-service fan-out** — a
second consuming service needing the same task stream, where one canonical broker beats N services reaching
into our tables. Softer trigger: **W sustained above a few hundred workers**, where connection count forces
PgBouncer and the simplicity argument starts to invert. Because everything goes through `QueueAdapter`,
migration is a new adapter plus an outbox relay with the worker loop and D7 state machine unchanged — but
D8's fairness policy would have to be re-expressed as a DB claim feeding a per-priority queue set, and that
re-expression is the real cost of the move.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Atomic eager pairing | 0 stranded partials and 0 double-consumed partials across 1,000 induced crashes at the D3 commit point | Chaos test: `kill -9` a worker inside the claim-and-enqueue transaction; assert `sum(partial.count) == F` for every completed job and no `consumed` partial without a live owning `reduce` task |
| Claim latency | p99 < 50 ms with 200 concurrent workers polling | `EXPLAIN (ANALYZE)` on the claim query + application histogram of claim round-trip |
| Sustained claim rate | ≥ 500 claims/sec on a single Postgres 16 with no-op tasks (≥10× the projected real rate) | Load harness enqueues 500k no-op tasks; measure completions/sec and `pg_stat_activity` lock waits |
| Zero lost tasks under worker loss | 100% of tasks from `kill -9`ed workers requeued within lease + reaper interval (≤ 2× lease) | Kill 50% of workers mid-job; assert job still completes with a correct result vector |
| Fairness (D8) | A 3-task job submitted behind a 27k-task job completes in < 60 s — it does not wait for the large job | Submit F=10 job after F=100k job; compare wall-clock to the small job run alone |
| No queue bottleneck | Queue wait time < 5% of mean task service time | `claimed_at - created_at` vs `done_at - claimed_at` from the `tasks` table |
| Adapter portability | An `SqsQueueAdapter` stub type-checks against `QueueAdapter` with no change to the worker loop | CI compile check; interface signature contains no Postgres-specific types |
