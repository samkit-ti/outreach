# ITD: DM-009 — Observability and the Live UI (Event Log + SSE)

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-002 (eager pairing, dynamic task DAG), DM-006 (state machine, leases, reaper), DM-007 (multi-job fairness), DM-008 (worker pool, desired vs actual W), `../02-hld.md`, `../CONTEXT-BRIEF.md`

---

## Problem Statement

The bonus asks for "a UI with updating logs: workers free/busy, jobs completed, jobs queued, and
anything else judged relevant". Two of the brief's critical aspects — *how the system decides a job is
finished* and *support submitting multiple jobs while jobs are ongoing* — are claims about behaviour
that are only believable if they are visible while running. A max **job** (F=100k, C=1M) is ≈20,000
leaf `map` **tasks** plus ≈5,000 `reduce` tasks over ~7 levels plus ≈2,000 `generate` tasks
(≈25k compute tasks total), so the UI has to show meaningful progress over tens of thousands of state
transitions without either lying or flooding the browser. Target: a state change is on screen within
1 s, per-**job** progress % is monotone non-decreasing and hits exactly 100% when the result file is
written, and 10 concurrent browser tabs cost one DB query per second in aggregate. Today there is no
event log and no UI.

---

## Context

- **The task DAG is not known in advance.** D3/DM-002 creates `reduce` tasks *eagerly*, whenever ≥5
  unconsumed **partials** exist for a job, and in drain mode with fan-in 2–4. So the total task count
  for a job *grows while the job runs* — from ⌈F/5⌉=20,000 at submit to ≈25,000 at the end. Any
  progress metric shaped as `done / total` therefore has a growing denominator and visibly regresses.
- **Task volume is the constraint on the transport, not the data volume.** Bytes stay in S3/MinIO
  (D6); the DB and queue carry URIs only. But ≈25k tasks × 2 transitions is ≈50k state changes per
  max job, so a design that pushes one frame per transition pushes ~50k frames.
- **The DB already holds the truth.** The `tasks` table *is* the queue (D5), and every transition is
  transactional (D7). Anything the UI shows must be derived from committed DB state, never from a
  worker's in-memory belief — otherwise the UI and the completion logic can disagree, and how
  completion is decided is a named critical aspect in the brief.
- **Workers report liveness by heartbeat** into the `workers` table (D10/DM-008), 10 s interval,
  30 s lease, 5 s reaper sweep (worst-case detection 35 s, DM-006). `free`/`busy` is `current_task IS NULL` among rows with
  `last_heartbeat > now() − 30 s`. **W** has a *desired* value (`system_config.desired_workers`)
  and an *actual* value that lags it during reconciliation, so the UI shows both (DM-008).
- **API is Node 22 / Express / TypeScript** (given), behind an ALB on AWS with a 60 s default idle
  timeout, or hit directly in docker-compose. Whatever transport we pick has to survive both.
- **Fairness must be observable** (DM-007): the demo submits a 25k-task job and a 3-task job and has
  to *show* both advancing, which means per-job rows, not one global progress bar.

---

## Alternatives

### UI polls REST endpoints every N seconds

The UI calls `GET /jobs` and `GET /system/stats` on a `setInterval` of 1–2 s and re-renders.

**Pros:**
- Genuinely the simplest thing that works: no long-lived connections, no server-side subscriber
  registry, no reconnect logic, stateless and load-balancer-agnostic.
- Naturally self-limiting — a slow or backgrounded tab just polls less; no server-side backpressure
  problem exists.
- Trivially cacheable and trivially debuggable with curl.

**Cons:**
- Latency is the poll interval by construction. At 2 s, a `worker.claimed` → `task.done` pair on a
  fast task can be entirely invisible, which undercuts the "updating logs" ask.
- Cost scales with tabs × endpoints: 10 tabs × 3 queries' worth of endpoint surface × 1 Hz = 30
  queries/sec of pure overhead,
  most returning unchanged data.
- Discrete snapshots lose the *sequence*. "Job B started while Job A was mid-flight" is exactly the
  multi-job claim being evaluated, and it reads as two unrelated frames rather than an ordered log.

### Server-Sent Events from an append-only event log **[CHOSEN]**

Every meaningful transition appends a row to an `events` table in the same transaction that makes the
change. `GET /events` is a `text/event-stream` HTTP response; the API pushes ordered frames; the
browser's built-in `EventSource` consumes them and auto-reconnects.

**Pros:**
- SSE is a plain HTTP/1.1 response in Express — no protocol upgrade, no extra library, no separate
  port: set the headers, `flushHeaders()`, then `res.write()` frames for the life of the request.
- Reconnect and gap-recovery are *in the standard*: `EventSource` retries automatically and replays
  the last `id:` it saw as a `Last-Event-ID` request header. Because our event ids are a monotone
  `BIGSERIAL`, resume is literally `WHERE id > $cursor` — the client cannot silently miss events.
- One-directional, matching the actual flow: everything client→server is already a REST call
  (submit job, set W). Nothing is being given up.
- The event log is independently valuable: an append-only, ordered, replayable audit of *why* the
  system concluded a job was finished — the question the brief asks — usable after the demo, not just during.
- Server-side cost decouples from client count: one 1 Hz aggregate query feeds N subscribers.

**Cons:**
- Long-lived connections need care in proxies: ALB idle timeout must exceed our keepalive interval,
  and Express's `compression` middleware must be disabled on this route or it buffers frames.
- Under HTTP/1.1 the browser allows ~6 connections per origin, so the UI must multiplex all channels
  onto one stream instead of one stream per widget.
- Requires an in-process subscriber registry, so a multi-replica API needs each replica to run its own
  ticker — fine, but it means the stream is not perfectly consistent across replicas.
- Text framing only; binary would need base64 (irrelevant here — we ship counters).

### WebSockets

Upgrade `/events` to a WebSocket and push JSON messages over it.

**Pros:**
- Bidirectional and lower per-message overhead, so a future interactive control plane (cancel a job,
  set W from the socket, request a targeted worker drain) would need no second mechanism.
- Mature libraries (`ws`, socket.io) and near-universal support; socket.io adds rooms, which would
  map neatly onto per-job channels.

**Cons:**
- Buys bidirectionality we do not need: our flow is strictly server→client, and every client→server
  action already has a REST endpoint with proper status codes and validation.
- Reconnect and replay are *not* in the protocol. socket.io provides them by adding its own framing
  layer plus a client bundle; raw `ws` means hand-writing backoff and a resume cursor — reimplementing
  what SSE gives free.
- The HTTP `Upgrade` handshake has to survive the proxy path: ALB supports it, but it needs explicit
  handling and is a well-known source of 400/502s behind misconfigured intermediaries.
- Harder to inspect: `curl -N` reads an SSE stream as text; a WS frame needs a special client.

### Full metrics stack: Prometheus + Grafana

Instrument the API and workers with a Prometheus client, scrape them, build Grafana dashboards.

**Pros:**
- The production-correct answer. Histograms of task duration, rate/increase over windows, retention,
  alerting, and per-worker time series that make heterogeneous worker speed obvious at a glance.
- Zero bespoke UI code; dashboards are configuration.
- Would give us proper SLI/SLO material (p99 task latency, queue-depth-age) that a hand-rolled panel
  will never have.

**Cons:**
- Two more containers plus dashboard provisioning, for a deliverable whose stated bonus is a UI with
  updating logs — the effort lands outside what is evaluated.
- Wrong granularity for the ask. Scrape intervals are 15–30 s and gauges are sampled, so
  "worker 3 just claimed task 8812" is structurally unavailable; Prometheus deliberately does not do
  per-event streams.
- Provides no *job-level* view: job progress and completion are business state living in Postgres,
  not a metric, so we would still build the job UI on top.

### Postgres `LISTEN`/`NOTIFY` pushed straight to clients

Emit `NOTIFY` inside the committing transaction; the API listens and forwards.

**Pros:**
- Push originates from the transaction itself, so latency is bounded by commit, not by a poll tick —
  no 1 Hz ticker at all.
- No extra infrastructure: it is already in the database we are already running.

**Cons:**
- Fire-and-forget with no history: a client (or an API replica) that is disconnected during a
  notification never learns of it, so reconnect-with-replay — the property that makes the UI
  trustworthy — is impossible without also keeping the `events` table.
- 8000-byte payload limit and a dedicated always-listening connection per API replica.
- It is not a browser transport, so a transport decision is still required. It is complementary,
  not an alternative: the natural use is as the ticker's wake-up signal, not as the client channel.

---

## Chosen: Append-only `events` table + SSE stream + static UI, with polling retained as fallback

**The decision (D11).** Every meaningful transition appends one row to an append-only `events` table
inside the transaction that performs it. `GET /events` returns `text/event-stream`; the API pushes
(a) low-frequency events individually and (b) a coalesced counters snapshot at 1 Hz. The UI is a small
static page using the browser's native `EventSource`, no framework, no build step. The same numbers
are exposed as plain REST (`GET /system/stats`, `GET /jobs`) and the UI falls back to polling
them at 2 s if `EventSource` is unavailable or fails repeatedly — so the fallback is not a second
implementation, just a second trigger for the same render function.

### Why SSE fits Express trivially

```ts
app.get('/events', async (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',          // defeat proxy buffering
  });
  res.flushHeaders();
  const cursor = Number(req.headers['last-event-id'] ?? 0);   // free gap recovery
  for (const e of await backfill(cursor)) send(res, e);        // WHERE id > cursor
  const unsub = hub.subscribe(res);
  const ka = setInterval(() => res.write(':ka\n\n'), 15_000);  // < ALB 60s idle
  req.on('close', () => { clearInterval(ka); unsub(); });
});
// frame: `id: 8812\nevent: task.done\ndata: {...}\n\n`
```

That is the entire transport: no upgrade handshake, no library, no second port. Two operational notes
that matter and are easy to miss — `compression` must be skipped for this route (it buffers frames
until a flush threshold), and the 15 s keepalive comment must stay below the ALB idle timeout or the
LB will cut an idle stream. Reconnect needs no code at all: `EventSource` backs off and resends
`Last-Event-ID`, and because ids are a monotone `BIGSERIAL` the resume query is `WHERE id > $cursor`.

**Why volume is not a problem.** ≈50k transitions per max job would be ~50k frames if pushed
one-per-event, which no browser panel can render usefully. So the stream is split by cardinality:
per-task events (`task.claimed`, `task.done`, `partial.committed`) are *written* to `events` — they
are the audit trail — but are *not* individually streamed. What streams is a 1 Hz coalesced
`stats.snapshot` frame plus the genuinely low-frequency events (`job.*`, `worker.*`, `task.failed`,
`task.lease_expired`, `config.*`) which are rare enough to be interesting one at a time. One ticker
runs one aggregate query per second and fans the result out to all subscribers, so 10 tabs cost one
query/sec, not 30.

### Progress % over a dynamic DAG

`done_tasks / total_tasks` is wrong here, and specifically: at submit, `total` is ⌈F/5⌉ = 20,000; by
the end it is ≈25,000 because eager pairing (D3) keeps adding `reduce` tasks. A user watching that
sees the bar *go backwards* every time the reduce forest grows. It is also non-comparable across jobs,
since a `generate` task and a level-6 `reduce` are wildly different amounts of work.

Instead we measure **file coverage**, which is monotone by construction because a **partial** carries
`(sum_vector, count)` where `count` is the number of input files it covers (D2):

- `mapped_files` = Σ `count` over partials created by `map` tasks — reaches exactly **F**.
- `reduce_inputs_consumed` = number of `partials` rows with `consumed_by IS NOT NULL`.
- `progress = (mapped_files + reduce_inputs_consumed) / (F + R_est)`, clamped to 99% until the
  `finalize` task commits, then exactly 100%.

`R_est` is the **analytic count of partials the ideal 5-ary tree consumes** (≈F/4), computed once at
submit. Both routes to that number agree, and it is worth being precise about which one the
denominator actually needs, because the obvious label is wrong. The series ⌈F/5⌉ + ⌈F/25⌉ + … ≈ F/4
enumerates the partials **produced** at each level (≈25,002 at F=100k). What
`reduce_inputs_consumed` counts is the partials **consumed** — every partial in the tree except the
root, i.e. L·k/(k−1) − 1 ≈ F/4 with L = ⌈F/5⌉ = 20,000 leaves and k = 5, so 24,999. The two differ by
exactly one node (the root, which nothing consumes), which is why the same ≈25,000 serves either way
and the total denominator is ≈1.25F. The label matters even though the number does not: the term is a
*consumption* count, and calling it "inputs produced per level" invites a future reader to go fix a
bug that is not there. Both numerator terms are
monotone non-decreasing: a committed partial is never uncommitted and a consumed partial is never
un-consumed. Retries cannot double-count because the aggregate is over `partials` *rows*, which are
keyed by producing task id and written idempotently (D7) — the count comes from state, not from
counting events. The one honest imprecision is `R_est`: drain-mode fan-in of 2–4 (D3) creates slightly
more reduce tasks than the ideal tree, so the true denominator can exceed the estimate — but DM-002
bounds that at ≤ ~7 extra reduces per job (one per tree level), i.e. **well under 1%** of a
≈125,000 denominator, not "a few percent". We still clamp at 99% and let `finalize` — the same
signal that decides the job is done — be the only thing that writes 100%, because a bound that
small is not what the clamp is defending against: the clamp exists so that nothing except the
completion decision itself can ever display 100%. Monotone and never-early beats linear-but-jittery: users
notice a bar going backwards far more than they notice one that is fractionally pessimistic mid-flight.

### Event schema sketch

```sql
CREATE TABLE events (
  id       BIGSERIAL PRIMARY KEY,   -- monotone; doubles as the SSE id / Last-Event-ID cursor
  ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
  type     TEXT        NOT NULL,    -- see taxonomy below
  job_id   UUID NULL, task_id UUID NULL, worker_id TEXT NULL,  -- workers.id is hostname:pid
  payload  JSONB       NOT NULL DEFAULT '{}'
);
CREATE INDEX ON events (id) INCLUDE (type);
CREATE INDEX ON events (job_id, id);
```

Append-only: no `UPDATE`, no `DELETE` except a retention trim (keep 7 days / 2M rows). Types:

| Family | Types | Streamed individually? |
|---|---|---|
| job | `job.submitted`, `job.running`, `job.completed`, `job.failed` | yes |
| task | `task.created`, `task.claimed`, `task.done` | no — folded into the snapshot |
| task (exceptional) | `task.failed`, `task.lease_expired`, `task.dead` | yes |
| partial | `partial.committed`, `partials.reduced` (payload: `input_ids`, `fan_in`, `count`) | no |
| worker | `worker.registered`, `worker.draining`, `worker.gone` | yes |
| config | `config.desired_workers_changed` | yes |

The 1 Hz snapshot frame:

```json
{ "workers": { "desired": 4, "actual": 4, "free": 1, "busy": 3, "draining": 0 },
  "queue":   { "pending": 812, "claimed": 3, "by_type": { "generate": 0, "map": 780, "reduce": 32, "finalize": 0 },
               "oldest_pending_age_sec": 4.2, "oldest_claimed_age_sec": 1.8 },
  "jobs":    { "queued": 1, "running": 2, "completed": 7, "failed": 0 },
  "throughput_tasks_per_sec": 11.4,
  "per_job": [ { "id": "…", "F": 100000, "C": 1000000, "status": "running",
                 "progress": 0.41, "partials_live": 63, "in_flight": 3, "eta_sec": 512 } ] }
```

**"jobs queued" needs a definition, because no job state is named `queued`.** The job states are
`pending / running / finalizing / completed / failed` (LLD §1), so the bonus's wording has to be
mapped onto something real rather than invented as a sixth state. In the snapshot frame: **`queued` =
running jobs that have ≥1 `pending` task and 0 tasks in flight** — a job the fleet is not currently
working on, which is exactly what a user means by "queued"; **`running` = jobs with ≥1 task in
flight**. The two are disjoint and their union is every non-terminal job, so the panel's counters
always add up, and a job visibly moves `queued → running` the moment a worker claims for it — which is
the multi-job fairness story (DM-007) rendered as a state change rather than as a number.

`throughput_tasks_per_sec` is `count(*) FROM events WHERE type='task.done' AND ts > now()-'10s'` / 10 —
which is the one place the event log is read as a metric rather than as an audit trail, and it is
cheap on the `(id)` index. `eta_sec` is remaining coverage ÷ trailing throughput, labelled an estimate.

**Two queue-age gauges, and which signals are worth waking someone for.**
`queue.oldest_pending_age_sec` (`max(now() − created_at)` over `pending` tasks) and
`queue.oldest_claimed_age_sec` (over `claimed` tasks) are added to the 1 Hz snapshot because they are
the only two numbers that distinguish "slow" from "stuck" — the first rises when nothing is claiming
(W=0, all workers wedged, a job filtered out of the claim query), the second rises when something
claimed and never finished (the wedged-but-heartbeating case DM-006 bounds with
`TASK_DEADLINE_SECONDS`). **These two, plus `backstop.fired` (DM-003's completion backstop, which
should never fire), are the alerting-worthy signals; everything else in the frame is diagnostic** —
useful once you are already looking, but not evidence on its own that anything is wrong.

### What the demo shows

1. **Fleet panel** — desired vs actual **W**, and per-worker rows (state free/busy/draining, current
   task type, `tasks_completed`). With one worker started at `WORKER_SLOWDOWN_FACTOR=5` (DM-008), its
   `tasks_completed` visibly lags while the job still finishes: heterogeneous speed absorbed, on
   screen, which is the DM-002 claim made observable.
2. **Queue panel** — pending/claimed by task type. The reduce count rising while map falls *is* eager
   pairing (D3) happening live, and it is the clearest evidence the fan-in is adaptive.
3. **Jobs panel** — queued / running / completed / failed counters plus one row per job with its own
   monotone progress bar. Submitting an F=3 job while an F=1000 job runs shows both bars advancing —
   the multi-job fairness claim (DM-007) demonstrated rather than asserted.
4. **Event log** — the last 200 low-frequency events, newest first. `worker.gone` followed by
   `task.lease_expired` followed by `task.claimed` is the crash-recovery story (DM-006) in three lines.
5. **W knob** — set W=0, watch pending climb and every job stall; set W=4 and watch it drain. The
   bonus, and the most convincing 20 seconds available.

### Why each rejection

*Polling* is the honest baseline and we keep it — as the fallback path, because it is strictly worse
on the two things the bonus names: latency (bounded by the interval, so short tasks are invisible) and
ordering (snapshots lose the sequence that makes the multi-job and crash-recovery stories legible).
*WebSockets* would cost an `Upgrade` handshake through the ALB and hand-written reconnect/replay to buy
bidirectionality we have no use for — every client→server action is already a validated REST call; SSE
gives auto-reconnect and `Last-Event-ID` resume for free, which is the exact feature WS lacks.
*Prometheus + Grafana* is the right production answer and is the documented evolution, but its
15–30 s scrape model structurally cannot show a per-event stream, and it has no concept of job-level
business state, so we would build this UI anyway on top of two extra containers.
*LISTEN/NOTIFY* is not actually a competing choice: without the `events` table there is no replay for a
reconnecting client, and it terminates at the API, not at the browser. It is the obvious first
optimisation — swap the 1 Hz ticker's timer for a NOTIFY wake-up — and needs no schema change to adopt.

### Failure condition

Revisit when any of: (a) the 1 Hz snapshot query stops being cheap — i.e. sustained task rate above
the D5 switch trigger of 5k tasks/sec, or `events` growth making the 10 s throughput window a seq
scan, at which point counters move to incrementally-maintained rollup rows or Redis; (b) the API runs
more than a handful of replicas, so per-replica tickers make the stream inconsistent between tabs and
a shared pub/sub (Redis, or NOTIFY as the fan-out bus) is required; (c) anyone needs *historical*
analysis — p99 task duration over a week, capacity planning, alerting — which is precisely where
Prometheus/Grafana stops being over-engineering and the event log becomes the wrong store;
(d) the UI needs to *control* individual workers (targeted drain, per-task cancel), which is the first
genuine client→server push requirement and the point at which WebSockets earns its handshake.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| End-to-end freshness | `task.done` commit → visible on screen < 1 s (p95) | timestamp diff, event `ts` vs browser render |
| Progress monotonicity | 0 decreases across a full F=1000 run | record every `progress` value from the stream; assert non-decreasing |
| Progress exactness | reaches exactly 1.0 iff `finalize` committed and the result file exists | compare final frame with `GET /jobs/:id` and the S3 object |
| Reconnect gap recovery | kill the API mid-job; on reconnect, 0 events missed | compare client-received ids with `SELECT max(id)` — contiguous |
| Fan-out cost | 10 open tabs ⇒ ≤1 stats query/sec total | `pg_stat_statements` call count for the snapshot query |
| Multi-job visibility | F=3 job submitted during an F=1000 job: both progress bars advance within 5 s | screen recording + per-job frames |
| Bonus coverage | workers free/busy, jobs completed, jobs queued all present and updating | visual check against the brief's bonus wording |
| Stream stability | 10 min idle stream behind the ALB stays open | keepalive comments logged, no reconnect events |
| Event write cost | `events` insert adds < 5% to task-commit transaction latency | benchmark commit path with the insert toggled off |
