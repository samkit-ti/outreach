# CHANGELOG

## v2.1 — 2026-08-10 · red-team pass on decision soundness

A third adversarial pass, aimed specifically at whether the v2 decisions hold as an
implementation contract: does every SQL statement reference a column that exists, does every
state transition have an owner, and is every mechanism reachable from the state it defends?
Five blockers and eight majors were accepted and fixed; the design's shape is unchanged.

### Blockers

1. **The `ON CONFLICT → skip pairing` shortcut reopened the stranding hole.** T2 skipped the
   pairing step when its partial `INSERT` conflicted, on the theory that a prior commit had
   already paired. But a task reaped *after* inserting its partial and *before* its commit
   landed is retried, and its retry's commit sees exactly that conflict — so the job could end
   with unconsumed partials and no future pairing trigger, a hole the advisory lock does not
   cover because the reaper is not a committer. Fix: T2 pairs after **every** successful fenced
   task-update regardless of the INSERT's result (pairing is idempotent under the lock), and
   T3 pairs too, under the same per-job lock, for every job whose task it requeues or kills.
   DM-003's backstop sweep is re-classified accordingly: redundant-but-retained instrumentation,
   not a bug detector that should page. (LLD §4 T2/T3, DM-002, DM-003)
2. **A failed `finalize` discarded a completed computation.** Three exhausted attempts flipped
   the job to `failed`, which is terminal *and* unclaimable — the claim query serves only
   `('running','finalizing')`, so no re-enqueued finalize could ever run. Fix: `finalize` gets
   `max_attempts=10` (it is one idempotent 8 MB read and a divide); the reaper's job-failure
   UPDATE excludes any job still holding an unconsumed `count == F` partial, emitting
   `job.needs_finalize` instead; the backstop may reset such a job to `finalizing` and
   re-enqueue. (LLD §4 T3, §8, DM-003, DM-006)
3. **`dedupe_key = 'map:{jobId}:{batchIdx}'` was not computable.** `batchIdx` appeared in no
   payload, and a spawn-time counter would give a retried `generate` different keys — every
   insert succeeding, duplicate map tasks, and a job count exceeding F. Fix: the `map` payload
   carries `fileIdxFrom`/`fileIdxTo` and the key is `'map:{jobId}:{fileIdxFrom}'`, a pure
   function of the generate range chunked by `K_FANIN`. (LLD §1, §2, DM-006)
4. **Nobody was specified to compute map `inputUris`.** Fix: stated explicitly — the `generate`
   task's commit transaction computes each spawned map task's payload, deriving `inputUris`
   from `jobs/{jobId}/inputs/{fileIdx}.csv` over its chunk via one shared key constant.
   (LLD §2, §4 T2, DM-006)
5. **`claimed_at` and `deadline_at` were read but never created, and the heartbeat took a
   client-supplied epoch.** Fix: both columns added to the `tasks` DDL and set by the claim
   query from the DB's `now()`; the heartbeat's deadline conjunct becomes
   `AND lease_expires_at < deadline_at`, fully server-side; the reaper reads `now() > deadline_at`.
   New standing rule: all lease/deadline arithmetic uses the DB's `now()` — workers never send
   timestamps. (LLD §1, §3, §4 T3)

### Majors

- **Per-task-type deadlines.** A flat 300 s was justified with the `map` constant, but a
  `generate` batch moves ~1,000 MB — ~20 s at 1×, ~200 s at the 10× slowdown the straggler demo
  configures — so a flat ceiling reaped healthy tasks. Now
  `{map:300, reduce:300, finalize:300, generate:1800}`. (LLD §3/§8, DM-006)
- **Claim query takes a window, not a point.** `LIMIT 1` made all idle claimers compute the same
  winner, so W−1 returned zero rows and slept with work pending. Now `LIMIT 16` (≈`ceil(W_max/2)`)
  in the CTE with `LIMIT 1` on the UPDATE's subselect, plus a partial index on
  `(job_id) WHERE status='claimed'` for the inflight aggregate. W bounds reconciled to
  W_max=32 everywhere. (LLD §1/§3, 01 A-7/§4, DM-007, DM-008)
- **SSE tail reads one second behind.** `BIGSERIAL` ids are assigned in order but become visible
  in *commit* order, so a full-speed tailer can advance past an id that has not committed yet and
  skip it permanently. The read is now `WHERE id > $cursor AND ts < now() - interval '1 second'`,
  and that lag is the resume guarantee; the "cannot silently miss events" and "contiguous"
  claims are corrected (rollback gaps are normal). (LLD §1, DM-009)
- **Two DB connections per worker.** The heartbeat thread cannot share the connection that runs
  T2 (multi-statement transaction; libpq is not thread-safe per connection), and it now stops
  before T2 opens — the worker loop's `with heartbeat_every(...)` wraps execute only. Pool
  sizing is `2W + API pool (10)`. (LLD §5/§8, DM-004, DM-008)
- **New T4 — executor failure.** Task status `'failed'` existed in the enum but nothing wrote or
  requeued it, so a worker-side exception had no path. T4 requeues the worker's own task to
  `pending` (or `dead` on the last attempt), fenced identically to T2, recording the cause in a
  new `tasks.last_error` column. The enum drops `'failed'`: requeue *is* the retry, and the claim
  query's fairness ordering supplies the spacing a backoff would. (LLD §1/§4, DM-006, CONTEXT-BRIEF D7)
- **`jobs.idempotency_key` added to the DDL** with a partial unique index, and T1's 0-row path
  now selects the existing id instead of assuming it. (LLD §1, §4 T1)
- **Reaper job-failure UPDATE guarded** with `AND jobs.status IN ('running','finalizing')` —
  without it the statement rewrote failed jobs every 5 s forever and could clobber a job that
  completed after its dead task. (LLD §4 T3)
- **The unreachable-by-invariant pairing state now has a detector.** T2's ELSE branch, when
  pending+claimed == 0, emits `job.stranded` with the partial set rather than silently
  no-op'ing. (LLD §4 T2, DM-003)

### Minors

Traffic vs resident bytes labelled distinctly (≈2.0 TB traffic, ≈1.0 TB resident; the storage-days
cost row now uses resident). F=1000 demo job recounted: 63 reduces, 284 tasks, ≈2.6 min at W=4
(01 §4, LLD §9). Partial index `ON events (ts) WHERE type='task.done'` for the throughput gauge
(LLD §1, DM-009). Two-key advisory lock form `pg_advisory_xact_lock(hashtext('pairing'),
hashtext($jobId::text))` with a note that int4 collisions only serialise unrelated jobs
(LLD §4, DM-002 and everywhere the lock is quoted). Root partial's GC noted (its `consumed_by`
stays NULL forever; the job-completion GC removes it with the objects) (LLD §7). Pairing entry
condition gains `AND job.status = 'running'` (LLD §4). `CHECK (priority = CASE type …)` on the
tasks DDL makes the ASC/DESC footgun unrepresentable (LLD §1).

## v2 — 2026-08-10 · hardened after two-track adversarial review

v1 was reviewed by two independent adversarial passes (correctness; completeness &
defensibility). v2 fixes everything accepted from both. v1 remains immutable in
`docs/v1/` for the record.

### Blockers fixed (correctness review)

1. **No job could ever finalize.** The claim query filtered `j.status='running'`, but
   the completion branch flips the job to `finalizing` before inserting the finalize
   task — which therefore was never claimable. Fix: claim serves
   `('running','finalizing')`; backstop sweep widened the same way. (LLD §3, §4)
2. **Mutual-decline pairing race stranded partials forever.** Two concurrent T2s could
   each see the other's task as `claimed` and each undercount the partial set (READ
   COMMITTED + SKIP LOCKED), so both took the `ELSE → nothing` branch — and pairing
   only runs on partial commit, so nothing ever re-fired. Reachable at F=7 with 2
   workers (the golden test). Fix: pairing serialised per job via
   `pg_advisory_xact_lock(hashtext(job_id))`; partials read becomes plain
   `FOR UPDATE ORDER BY created_at`. (LLD §4, DM-002, DM-003)
3. **Heartbeat unfenced against the reaper.** The reaper requeued tasks without
   rotating `lease_token`, and the heartbeat's only stated guard was that token. Fix:
   heartbeat requires `lease_token=$mine AND status='claimed'`; reaper sets
   `lease_token=NULL` on requeue. Added `TASK_DEADLINE_SECONDS` (absolute ceiling) so
   a wedged-but-heartbeating worker can't hold a task forever. (LLD §3/§4, DM-006)
4. **Priority sort inverted between documents.** DM-007's SQL said `priority DESC`
   against the LLD's finalize=0 numbering — which would run generate first, reversing
   the argued policy. Fix: `ASC` everywhere. (DM-007, LLD §3)

### Majors fixed

- Claim query rewritten: per-claim `inflight` CTE instead of a correlated subquery per
  pending row (v1's form scanned up to 20k rows per claim and couldn't use the index).
- Result delivery decided and owned by DM-005: `302` → 15-min pre-signed URL,
  `?inline=1` proxy for the demo; completion discovered via SSE `job.completed` or
  polling. (v1 self-contradicted between HLD/LLD and DM-005.)
- `finalizing → completed` transition made an explicit fenced CAS; deterministic-key
  rule restated honestly (result key is job-derived, safe via the finalize CAS).
- Admission control (`413` over `MAX_JOB_BYTES`, `429` over `MAX_ACTIVE_JOBS`),
  `Idempotency-Key` on `POST /jobs`, API conventions (error taxonomy, keyset
  pagination), `inputUris[]` so the prompt's F=2 worked example is a first-class test.
- READ COMMITTED isolation stated with the reason it suffices; concurrency tests now
  pin interleavings (two connections + injected sleep against the advisory lock).
- K=5 canonical reading unified (logical fan-in limit; streaming honours the byte
  reading; `generate` exempt with the GEN_BATCH→5 knob named). (01 §A-8, DM-008)
- DM-010 reframed honestly: numpy already does pairwise summation — distribution is
  accuracy-*neutral* vs numpy; the ~10⁴ win is only vs a naive serial loop.
- Intermediate-traffic figures reconciled (~200 GB written total; 160 GB is level 0
  alone); tree-depth success metric corrected (F=10³→4, 10⁴→5, 10⁵→7 levels);
  "3,125 files ≈ 15% of the job" corrected to 3.1%; lease constants (30/10/5)
  propagated to DM-008/DM-009; envelope honesty note (true maxima 99,999/999,999).
- Progress denominator: R_est relabelled (partials *consumed* by the ideal tree) and
  drain-mode error bounded at «1% (was "a few percent", contradicting DM-002).
- Task service-time model added (one constant: ~2.2 s per map task at ~50 MB/s) with
  makespan projections; max-job AWS cost estimate.
- events insert fixed to the real columns (`type`, `payload`; event `job.submitted`);
  stall SLIs added (`oldest_pending_age_sec`, `oldest_claimed_age_sec`); "jobs queued"
  defined; DM-004 now answers its own operational cons (fillfactor/autovacuum,
  archival, LISTEN/NOTIFY, PgBouncer); mermaid diagrams hardened for GitHub rendering;
  security section covers the docker.sock mount, SSRF posture, pre-signed TTL, and the
  unauthenticated worker-control endpoint.
- **New: DM-011** — build-vs-off-the-shelf (Spark/Dask/Temporal/Celery), the framing
  question v1 never asked.

## v1 — 2026-08-09 · initial full design

Requirements & assumptions, HLD, LLD, ITDs DM-001…DM-010, decision journey, reading
list, interactive simulator.
