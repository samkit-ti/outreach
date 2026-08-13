# The Complete Trace — One Job Through the Entire System, Atomic Steps

Read this top to bottom and you have walked every mechanism in the system exactly
once: submission, validation, claiming, heartbeats, streaming execution, the fenced
commit, eager pairing, a worker crash with lease recovery, drain mode, the
completion proof, the finalize CAS, and result delivery.

## The setup

- **Job:** F = 7 files, C = 4. File *i* contains `[i, 2i, 3i, 4i]`.
  Column sums = (1+2+…+7)·[1,2,3,4] = 28·[1,2,3,4] = **[28, 56, 84, 112]**.
  Expected result: ÷7 → **[4, 8, 12, 16]**.
- **Fleet:** W = 2. `w-fast` (1 s/file), `w-slow` (3 s/file). K = 5.
- **Files pre-exist** at `s3://distributed-mean/fixtures/run1/1.csv … 7.csv`
  (the harness put them there — it plays the federated nodes).
- Leases 30 s, heartbeats 10 s, reaper every 5 s, deadline 300 s.

---

## Phase 1 — Submission (t = 0.0)

**Step 1.** Client sends:
```
POST /jobs   {"inputUris": ["s3://…/1.csv", …, "s3://…/7.csv"], "c": 4}
```

**Step 2.** The API validates, in order, before touching the database:
shape (array of strings, integer c) → ranges (2 ≤ F=7 ≤ 99,999; 2 ≤ c=4 ≤ 999,999)
→ **duplicates** (a repeated URI would count one file twice — reject 422) →
**allow-list** (every URI under `s3://distributed-mean/` — otherwise 422 naming the
offender; this is the anti-SSRF gate, since URIs are caller-supplied) → **size**
(7×4×8 bytes ≪ MAX_JOB_BYTES) → **admission** (active jobs < 8, else 429).
Deliberately NOT validated: whether the objects exist — that would be F round-trips
on the submit path; a missing file is a *runtime* failure with retries.

**Step 3 — transaction T1.** One atomic transaction:
```sql
BEGIN;
INSERT INTO jobs (id, f, c, status) VALUES ('J', 7, 4, 'running');
-- chunk the URI list in order by K=5:
INSERT INTO tasks (id,job_id,type,status,priority,payload) VALUES
 ('M1','J','map','pending',2, '{files 1-5}'),   -- inputUris[0..4]
 ('M2','J','map','pending',2, '{files 6-7}');   -- inputUris[5..6]
INSERT INTO events (type,job_id) VALUES ('job.submitted','J');
COMMIT;
```
Everything or nothing: there is no instant where the job exists half-submitted.
Because ALL map tasks are born in this one transaction, no dedupe machinery for task
creation needs to exist. API returns `202 {"jobId":"J"}`.

**State:** jobs: J(running). tasks: M1(pending), M2(pending). partials: —.

## Phase 2 — Claiming (t ≈ 0.1)

Both workers have been idle-polling (every ~500 ms, jittered). Each runs the claim
statement — the queue is this one statement:

**Step 4.** `w-fast` claims. The SQL: compute in-flight counts per job (for fairness
— both zero here), select up to 16 candidate pending tasks ordered by
(job's in-flight ASC, priority ASC, age), **lock them, skipping rows other claimers
hold**, update the first one:
```sql
UPDATE tasks SET status='claimed', worker_id='w-fast', attempts=1,
  lease_token='tok-A',                    -- fresh random fence, every claim
  claimed_at=now(), deadline_at=now()+'300 s', lease_expires_at=now()+'30 s'
WHERE id=(first surviving candidate) RETURNING …;
```
→ gets **M1**. Every timestamp came from the *database's* clock — workers never send
time (clock skew can't corrupt lease math).

**Step 5.** `w-slow`'s claim runs concurrently; the row-skip means it doesn't wait on
w-fast's locked candidates → gets **M2** with `lease_token='tok-B'`.

**State:** M1(claimed, w-fast, tok-A), M2(claimed, w-slow, tok-B).

## Phase 3 — Execution on w-fast (t = 0.1 → 5.1)

**Step 6.** w-fast starts its **heartbeat thread** — on its own second DB
connection (the main connection will later hold a multi-statement transaction; they
can't share). Every 10 s:
```sql
UPDATE tasks SET lease_expires_at = now()+'30 s'
WHERE id='M1' AND lease_token='tok-A' AND status='claimed'
  AND lease_expires_at < deadline_at;    -- can never extend past the 300s ceiling
```

**Step 7 — streaming fold.** The executor never holds 5 files:
```
acc = [0,0,0,0]
GET 1.csv → +[1,2,3,4]   → acc=[ 1, 2, 3, 4]
GET 2.csv → +[2,4,6,8]   → acc=[ 3, 6, 9,12]     ← each file: fetched, folded, freed
GET 3.csv               → acc=[ 6,12,18,24]
GET 4.csv               → acc=[10,20,30,40]
GET 5.csv               → acc=[15,30,45,60]      n = 5
```
Each fetch passes the read guard (URI in allow-list or own bucket). Each value is
validated: parse as float64, length must equal C=4, values finite — a mismatch names
the URI in the error.

**Step 8.** PUT the partial — **before** the DB transaction, to a **deterministic
key**: `jobs/J/partials/M1.f64` (32 bytes: [15,30,45,60] as raw float64). The key is
derived from the task id, so if this task ever re-runs, the retry overwrites this
object with identical bytes — that's the entire idempotency mechanism, in the name.
The write guard confirms the key is under `jobs/J/` (a task can't write outside its
job).

**Step 9.** Heartbeat thread **stopped and joined** — T2 is about to open.

## Phase 4 — The fenced commit + eager pairing, T2 (t = 5.1)

**Step 10.** One transaction, order load-bearing:
```sql
BEGIN;
-- (a) the fence: am I still the owner?
UPDATE tasks SET status='done' WHERE id='M1'
  AND lease_token='tok-A' AND status='claimed';        -- 1 row ✓ (0 ⇒ rollback, discard)
-- (b) record the partial (idempotent: at most one per producing task)
INSERT INTO partials (id,job_id,uri,count,produced_by)
  VALUES ('P1','J','…/M1.f64',5,'M1') ON CONFLICT (produced_by) DO NOTHING;
-- (c) THE PAIRING STEP — serialized per job:
SELECT pg_advisory_xact_lock(hashtext('pairing'), hashtext('J'));
SELECT … FROM partials WHERE job_id='J' AND consumed_by IS NULL
  ORDER BY created_at FOR UPDATE;                      -- → {P1}, one row
SELECT count(*) FROM tasks WHERE job_id='J'
  AND status IN ('pending','claimed');                 -- → 1  (M2 still out there)
```
Branch logic: 1 partial < 5 → not a full merge; other work in flight → not drain
mode; count 5 ≠ 7 → not complete. **Do nothing — safely**, because "work in flight"
guarantees another commit (and another pairing evaluation) is coming. COMMIT.

**Progress right now:** coverage = (5 mapped + 0 consumed)/(7 + 2 estimated merge
inputs) = 5/9 ≈ **56%** — computed from partial rows (state), so it can only move
forward.

## Phase 5 — The crash (t = 6.0) 💥

**Step 11.** `w-slow` has fetched file 6 and is folding when its container is
killed. No goodbye: its heartbeat thread dies with it. M2 sits `claimed`,
lease expiring at ~30.1.

**Step 12.** w-fast, idle, polls: claim finds nothing (M2 is claimed, not pending).
The system is quiet but *not* stuck — a lease is ticking.

**Step 13 — the reaper (t ≈ 35).** Every 5 s it sweeps; at the first pass after
30.1:
```sql
UPDATE tasks SET status='pending', worker_id=NULL,
  lease_token=NULL,               -- ← rotate the fence: tok-B can never match again
  lease_expires_at=NULL
WHERE status='claimed' AND lease_expires_at < now();    -- M2 requeued, attempts stays 1
INSERT INTO events … ('task.lease_expired');
```
Then — because the reaper touched job J — it runs **the same pairing step** under the
same per-job lock (nothing to do here: 1 partial, M2 now pending). This is what makes
the pairing triggers *exhaustive*: every commit pairs, and the reaper pairs for every
job it touches — no state exists from which no future pairing evaluation is scheduled.

**Step 14.** w-fast's next poll claims M2 (attempts 1→2, fresh `tok-C`, fresh lease).
Suppose the zombie w-slow had somehow PUT `…/M2.f64` before dying — irrelevant:
w-fast will overwrite it with identical bytes. Suppose w-slow revived and tried to
commit — its fence (`lease_token='tok-B'`) matches zero rows; it discards its work.

**Step 15.** w-fast executes M2: files 6,7 → acc = [6+7, 12+14, 18+21, 24+28] =
**[13, 26, 39, 52]**, n = 2. PUT `jobs/J/partials/M2.f64`.

## Phase 6 — Drain mode creates the merge (t ≈ 41)

**Step 16 — T2 for M2.** Fence with tok-C ✓ → insert P2(count=2) → job lock →
unconsumed = {P1(5), P2(2)} → in-flight count = **0** → fewer than 5 partials, BUT
nothing is running and nothing pending → **drain mode**:
```sql
INSERT INTO tasks VALUES ('R1','J','reduce','pending',1,   -- priority 1 beats maps
   '{partialIds:[P1,P2], partialUris:[…M1.f64, …M2.f64]}');
UPDATE partials SET consumed_by='R1' WHERE id IN ('P1','P2');   -- consumed EXACTLY here,
COMMIT;                                                          -- at creation, not at run
```
Consuming at *creation time* inside this same transaction is what makes a redelivered
R1 harmless later — its input set is frozen; a duplicate run re-reads the same two
partials and overwrites the same output key.

Without drain mode, this is the moment the system would deadlock forever: two
partials waiting for a fifth that can never exist.

**Progress:** (7 mapped + 2 consumed)/9 = 9/9 → **clamped to 99%** — only the
finalize may say 100%.

## Phase 7 — The merge and the completion proof (t ≈ 41 → 42)

**Step 17.** w-fast claims R1 (only pending task). Executes: GET both partials
(read guard: own bucket ✓), validate length 4 each,
[15,30,45,60] + [13,26,39,52] = **[28, 56, 84, 112]**. PUT `jobs/J/partials/R1.f64`.

**Step 18 — T2 for R1, where the job proves itself done.** Fence ✓. The new
partial's count is computed **from the database, not the worker**:
`SELECT sum(count) FROM partials WHERE consumed_by='R1'` → 5+2 = **7**. Insert
P3(count=7, produced_by=R1). Job lock. Unconsumed = {P3}. In-flight = 0. And now:

> exactly one unconsumed partial · its count (7) = F (7) · nothing in flight
> ⇒ **the conservation proof fires.** P3 must contain every file exactly once.

Acting on it is a compare-and-swap, so only one observer can ever arm the ending:
```sql
UPDATE jobs SET status='finalizing' WHERE id='J' AND status='running';  -- 1 row ⇒ I arm it
INSERT INTO tasks VALUES ('FZ','J','finalize','pending',0,      -- priority 0: front of queue
   '{partialUri:…/R1.f64, f:7, c:4}');   -- max_attempts=10: a proven answer is unkillable
COMMIT;
```
(The claim query serves jobs in 'running' **and 'finalizing'** — the one-line fix
without which FZ would be invisible and every job in the system would hang at 99%.)

## Phase 8 — Finalize and delivery (t ≈ 42 → 43)

**Step 19.** w-fast claims FZ. GET `…/R1.f64` → [28,56,84,112] ÷ 7 →
**[4, 8, 12, 16]** → PUT `jobs/J/result.csv` (key derived from the *job* — safe
because the CAS guaranteed exactly one finalize ever exists).

**Step 20 — T2, finalize branch.** Fence ✓ →
```sql
UPDATE jobs SET status='completed', result_uri='…/result.csv', completed_at=now()
WHERE id='J' AND status='finalizing';                    -- the mirror CAS
INSERT INTO events … ('job.completed');
COMMIT;
```

**Step 21.** The dashboard's SSE stream (which has been tailing the events table
one second behind commit-time, so it can never skip an uncommitted row) shows
`job.completed`; the progress bar writes its first and only 100%.

**Step 22.** Client: `GET /jobs/J/result` → **302** redirect to a 15-minute
pre-signed URL — the client downloads straight from object storage; the API never
touches the bytes. (`?inline=1` would proxy instead, for curl.) Body:
```
4.0
8.0
12.0
16.0
```

**Final state:** jobs: J(completed). tasks: M1 done(1 attempt), M2 done(2 attempts),
R1 done, FZ done. partials: P1,P2 consumed_by=R1; P3 unconsumed (the root — GC'd with
the objects later). One worker died mid-job; the answer is exact.

---

# Part 2 — The fork points: every edge case, anchored to its step

The spine above is the story you *tell*; these forks are the answers to "okay, but
what if — right there — X happened instead?" Each is anchored to the step where the
interviewer would interrupt.

## Fork @ Step 2 — hostile submissions (the front door)

- **Duplicate URI** in the list → 422 immediately. Why it matters: a repeated file
  would be counted twice and silently skew the mean — this is a *correctness* check
  wearing a validation costume.
- **URI outside the allow-list** (`s3://evil-bucket/…`) → 422 naming the offender.
  Caller-supplied URIs are an SSRF vector; the allow-list is checked here AND again
  by the worker at read time (the object behind a URI can change between checks).
- **F×C×8 over the size cap** → 413. **A ninth active job** → 429 with Retry-After.
  Both checked *before* any write — a rejected job leaves zero residue.
- **The same POST retried** (network blip, client retry) with an `Idempotency-Key`
  header → the transaction finds the existing key and returns **200 with the
  original jobId** — no twin job, no duplicate work. Without the header, a duplicate
  is a distinct job *by design* (two users may legitimately want the same mean).
- **Deliberately NOT checked: object existence.** That would be F round-trips on the
  submit path — the exact serialize-everything-through-one-node sin the design
  exists to avoid. Missing files are a runtime failure with retries (next fork).

## Fork @ Step 7 — a bad input (file 3 is missing, or has 5 values instead of 4)

The GET 404s (bounded timeouts: 5 s connect / 30 s read — a hung store fails the
task rather than hanging the worker), or the length check fails. The executor raises
an error **naming the URI**. The failure path (T4) is fenced exactly like a commit:

```sql
UPDATE tasks SET status='pending', worker_id=NULL, lease_token=NULL,
  last_error='PermanentInputError: s3://…/3.csv: declared C=4 but file has 5 values'
WHERE id='M1' AND lease_token='tok-A' AND status='claimed';
```

Requeue IS the retry — attempts were already charged at claim. Attempts 2 and 3 hit
the same wall (a missing file doesn't come back), the third flips the task to
**dead**, and the reaper fails the job loudly, the offending URI preserved in
`last_error` and surfaced in `GET /jobs/:id`. The mean is never computed from
partial data — the job fails *honestly* instead of answering *wrongly*.

## Fork @ Step 6 — the wedged-but-heartbeating worker

Nastier than a crash: w-fast's GET hangs indefinitely, but its heartbeat thread —
a separate thread on a separate connection — keeps chirping "alive!" every 10 s.
Leases alone would extend forever. Two guards close it: the heartbeat SQL itself
refuses to extend past the absolute ceiling (`AND lease_expires_at < deadline_at`),
and the reaper reclaims on `now() > deadline_at` regardless of heartbeats. Ceiling:
300 s. **Liveness never depends on a worker's self-report.**

## Fork @ Step 10 — the simultaneous-commit race (the deepest probe)

Variant setup: both maps finish at the same instant; their T2s open concurrently.
**Without the per-job lock** (the v1 bug, reachable at exactly this F=7/W=2 shape):
each transaction's snapshot still shows the *other* task as claimed, and the
row-skipping read hides the other's uncommitted partial — so worker A sees "1
partial, work still in flight → not my problem," worker B concludes the same
symmetrically, **both commit having merged nothing**, and since merging is only
triggered by commits, no trigger ever fires again. Stranded forever at 99%.

**With the lock:** A's pairing enters first; B's transaction *waits milliseconds* at
`pg_advisory_xact_lock`; when A commits, B proceeds and now sees the complete
picture — A's partial committed, A's task done, nothing in flight → **drain mode
fires from B's own transaction**. The rule the lock enforces: *the last committer
provably has the complete picture.* There's a two-connection test pinning exactly
this interleaving.

## Fork @ Step 5 — a second job arrives mid-run (graded: fairness)

Job K (F=2, tiny) is submitted while J's tasks are mid-flight. The next free
worker's claim orders candidates by **in-flight-tasks-per-job ascending**:
J has 1–2 claimed, K has 0 → **K's map wins the very next claim**. K finishes in
roughly its own ~5 s of work while J continues around it — under plain FIFO, K would
have queued behind every remaining task of J. The big job's loss: a few
worker-seconds, ~0.01% at scale. Fairness is one ORDER BY, not a scheduler.

## Fork @ Step 5b — the operator scales the fleet (bonus 1)

Mid-job: `PATCH /system/workers {"desired": 4}` → the API writes one row and
returns. The supervisor's next 5-second pass compares desired (4) to actual (2) and
starts two containers; they register and their first claims succeed within a second —
no draining, no rebalancing, pull just absorbs them. Scale *down* is the polite
version: SIGTERM → finish the task in hand → commit → deregister — and if the
container is killed rudely anyway, the lease path (Step 13) already covers it.
**Correctness never depends on the graceful path.**

## Fork @ Step 3 — the degenerate job (F ≤ 5)

F=4: T1 creates exactly ONE map task. Its commit inserts a partial with count=4=F,
pairing finds one unconsumed partial, count equals F, nothing in flight → straight
to the finalize CAS. **No merge ever runs; no special-case code exists** — the
general machinery degrades to the trivial case by itself. (The brief's own F=2
example is this fork — it's the first test in the suite.)

## Fork @ Step 16 — the merge task is redelivered

R1's worker stalls; the lease expires; R1 requeues; another worker runs it — while
the original may still finish. Why nothing corrupts: R1's **input set was frozen at
creation** (P1 and P2 were marked consumed in the transaction that created R1 —
consumption-at-creation, not at execution), so both executions read the same two
partials and write byte-identical bytes to the same key `…/R1.f64`. The fence lets
exactly one commit count; the loser's late commit matches zero rows. Duplicates are
harmless *by construction*, not by luck.

## Fork @ Step 19 — the finalize itself fails

S3 blips during the result PUT → T4 requeues it. Finalize gets **10 attempts** (it's
one idempotent 8 MB read and a divide) versus 3 for everything else. And if it
somehow died anyway: the reaper **refuses to fail a job that still holds a count=F
partial** — it emits a `needs_finalize` alert, and the backstop can re-arm the
finalize. Principle: *a computation that has proven itself complete is unkillable by
retry bookkeeping.* (The v1 design discarded a finished answer here — a review catch.)

## Fork @ Step 21/22 — the client-side edges

- **Result requested early** → 409 with the job's current status; completion is
  announced by the `job.completed` SSE event or polling.
- **Dashboard disconnects and reconnects** → the browser auto-resends
  `Last-Event-ID`; the tail resumes with `id > cursor` — and can't have skipped
  anything, because it only ever reads events older than one second (ids are
  assigned in order but become *visible* in commit order; the lag is the guarantee).
- **The progress bar** never moved backwards through any of this — it's computed
  from partial rows (state), clamped at 99%, and only the finalize writes 100%.

## Coverage map — design edge-case table → where it lives here

| Edge case | Where |
|---|---|
| F ≤ 5 / brief's F=2 example | Fork @ Step 3 |
| F not divisible by 5 | Spine (5+2 chunks; drain merge) |
| Drain mode / tail stall | Spine Step 16 |
| Simultaneous last commits | Fork @ Step 10 |
| Worker crash / lease / reaper | Spine Steps 11–14 |
| Wedged-but-heartbeating | Fork @ Step 6 |
| Zombie commit discarded | Spine Step 14 |
| Redelivered merge | Fork @ Step 16 |
| Duplicate POST / idempotency | Fork @ Step 2 |
| Oversized / flooding / SSRF | Fork @ Step 2 |
| Bad input URI → honest failure | Fork @ Step 7 |
| Early result request | Fork @ Step 21 |
| Queue quiet ≠ done | Spine Step 12 |
| Fairness under concurrency | Fork @ Step 5 |
| W reconfigured mid-job | Fork @ Step 5b |
| Failing finalize / answer preservation | Fork @ Step 19 |
| SSE resume without loss | Fork @ Step 21 |
| Progress monotonicity | Spine + Fork @ Step 21 |

---

## The trace in one breath

Validate at the door → one transaction births the job and all its maps → workers
pull with fenced leases → stream-fold, PUT to a name derived from the task, then
commit-and-pair under the job lock → a crash is just a lease that stops being
renewed → drain mode merges the stragglers → counts conserve until one partial
confesses to being the answer → a CAS arms one finalize → divide, mirror-CAS,
pre-signed URL. Every arrow either commits atomically or retries harmlessly.
