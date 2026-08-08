# Distributed Mean — High-Level Design (v1)

**Date:** 2026-08-09 · **Author:** Samkit Shah · **Status:** v1 (iterating)
**Reads with:** `01-requirements-and-assumptions.md` · decisions justified in `itds/DM-001…DM-010`

---

## 1. Design thesis

The job is a **distributed fold**: `mean_i = (Σ_f file_f[i]) / F`. Because sums are
associative and commutative, partial sums can be combined **in any order, in any
grouping, by any worker** — so the system never needs a barrier, a coordinator that
tracks the whole computation, or any notion of "which worker owns which piece."

Everything else follows from three commitments:

1. **Partials carry `(sum-vector, count)`, never means** (DM-001/DM-010). Combining is
   order-independent and exact; divide by F once at the end.
2. **A partial is file-shaped**, so the K=5 RAM constraint applies to reduction too →
   reduction is a recursive **5-ary tree** executed *through the same queue* as
   everything else (DM-001).
3. **Workers pull; the tree is never pre-built.** Reduce tasks are created *eagerly*
   whenever ≥K partials exist (or fewer, in drain mode) — so fast workers reduce
   while slow workers are still mapping, and no branch waits on a specific child
   (DM-002/DM-003).

One sentence for the interview: *"I turn the job into a bag of idempotent tasks whose
partial results are closed under a 5-ary merge, let heterogeneous workers pull from
the bag, and completion is the theorem that a partial covering all F files is the
answer."*

## 2. Architecture

```mermaid
flowchart LR
    U[User / UI] -->|"POST /jobs {F,C}\nGET /jobs/:id\nSSE /events"| API

    subgraph CONTROL PLANE
        API["API\nNode 22 · Express · TS\n(stateless)"]
        PG[("Postgres 16\njobs · tasks(=queue) · partials\nworkers · events")]
        SUP["Supervisor\nreconciles W\n+ lease reaper"]
    end

    subgraph DATA PLANE
        S3[("Object store\nMinIO local / S3 on AWS\ninputs · partials · results")]
    end

    subgraph WORKER FLEET
        W1["Worker 1 (py)"]
        W2["Worker 2 (py)"]
        WN["Worker W (py)"]
    end

    API <--> PG
    SUP <--> PG
    W1 & W2 & WN <-->|"claim / heartbeat / commit\n(SKIP LOCKED)"| PG
    W1 & W2 & WN <-->|"GET inputs & partials\nPUT partials & result"| S3
    API -->|stream result| S3
```

**Separation of planes** is the load-bearing property: the control plane moves
kilobytes (task rows, URIs); the data plane moves the ~1.6 TB. Postgres never sees a
vector; S3 never sees a state machine.

| Component | Responsibilities | Deliberately NOT responsible for |
|---|---|---|
| API (Node/Express/TS) | validate & create jobs; enqueue seed tasks; serve status/result/SSE; write `desired_workers` | any computation; holding job state in memory (stateless → scalable, restart-safe) |
| Postgres | source of truth: job/task/partial state; **the queue** (SKIP LOCKED); fairness ordering; events | carrying data-plane bytes |
| Object store | input files, partial vectors, result files | consistency of the computation (control plane owns that) |
| Workers (Python) | claim task → execute (generate/map/reduce/finalize) → commit + eager-pairing step | choosing what to work on (the claim query decides), tracking siblings |
| Supervisor | reconcile actual worker count → `desired_workers`; requeue expired leases (reaper) | scheduling decisions |
| UI | render SSE stream: workers free/busy, jobs queued/running/done, per-job progress | anything write-path except W and job submission |

## 3. The task model

Four task types, one queue, uniform claiming (full schemas in LLD):

| Type | Reads | Writes | Fan |
|---|---|---|---|
| `generate` | — | ~50 input files | 1 job → ~F/50 tasks |
| `map` | ≤5 input files | 1 partial `(Σ, n≤5)` | F/5 tasks |
| `reduce` | 2–5 partials | 1 partial `(Σ, Σn)` | created dynamically |
| `finalize` | 1 partial with n=F | result file (÷F) | exactly 1 |

### Eager 5-ary reduction (the centerpiece)

There is **no pre-built tree**. When any worker commits a partial, in the *same
transaction* it runs the pairing step:

```
≥ 5 unconsumed partials for job?         → claim 5, insert reduce task
else: job has no pending/running tasks
      and ≥ 2 partials?                  → claim them (2–4), insert reduce  (drain mode)
else: exactly 1 partial and n == F?      → insert finalize
```

```mermaid
flowchart TB
    subgraph "logical result (emerges dynamically, never materialized as a plan)"
        direction TB
        M1["map: files 1–5 → P(Σ,5)"] --> R1["reduce → P(Σ,25)"]
        M2["map: files 6–10 → P(Σ,5)"] --> R1
        M3["..."] --> R1
        R1 --> R2["reduce → P(Σ,125)"]
        R1b["reduce → P(Σ,25)"] --> R2
        R2 --> FZ["finalize: P(Σ,F) ÷ F → result.csv"]
    end
```

Why eager beats a fixed tree: a fixed tree makes reduce node X wait for its *specific*
5 children — one slow child stalls the branch even though 50 other partials are ready.
Eager pairing merges *whatever is ready*, so a straggler's output is simply picked up
by whichever merge happens next. Stragglers delay only their own ~8 MB of work, never
a branch (DM-002).

**Completion is semantic, not counted** (DM-003): counts are conserved — generate/map/
reduce all preserve the total number of covered files — so `n == F` on a lone
unconsumed partial is a *proof* the job is done, valid under retries, dynamic task
creation, and any interleaving. Counters exist only to feed the UI.

## 4. Job lifecycle (happy path)

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant A as API (TS)
    participant PG as Postgres (state+queue)
    participant Wk as Worker (py, ×W)
    participant S3 as Object store

    U->>A: POST /jobs {F: 1000, C: 100000}
    A->>PG: INSERT job + generate tasks (1 txn)
    A-->>U: 202 {jobId}

    loop until queue empty (all workers, concurrently)
        Wk->>PG: claim next task (SKIP LOCKED, fairness ORDER BY)
        alt generate
            Wk->>S3: PUT 50 input files
            Wk->>PG: commit done + INSERT map tasks for batch
        else map
            Wk->>S3: GET ≤5 files
            Wk->>S3: PUT partial (Σ, n≤5)
            Wk->>PG: commit done + INSERT partial row + eager-pairing step
        else reduce
            Wk->>S3: GET 2–5 partials
            Wk->>S3: PUT merged partial (Σ, Σn)
            Wk->>PG: commit done + INSERT partial row + eager-pairing step
        else finalize (n == F)
            Wk->>S3: GET final partial, PUT result.csv (÷F)
            Wk->>PG: job → completed
        end
    end

    U->>A: GET /jobs/{id}  →  {status: completed, progress: 100}
    U->>A: GET /jobs/{id}/result
    A->>S3: stream result.csv
    A-->>U: 200 (file)
```

Failure path in one line (details DM-006): every claim carries a **lease**; a crashed
worker's lease expires, the reaper flips the task back to `pending`, and because every
task writes to a **deterministic object key**, the retry overwrites harmlessly.
At-least-once delivery + idempotent effects ≡ effectively-once outcome.

## 5. How each graded "critical aspect" is answered

| Prompt's criterion | Design answer |
|---|---|
| F > 5, no 1:1 job↔queue-item | Job explodes into ~F/50 generate + F/5 map + dynamic reduce tasks on one queue (§3). |
| Efficient distribution | Pull-based claiming (self-balancing under heterogeneous speeds) + adaptive fan-in + priority `finalize>reduce>map>generate` (DM-002, DM-007). |
| Deciding "job finished" | Conservation invariant: lone partial with n=F is the result — proof, not heuristic (DM-003). |
| Multiple concurrent jobs | Fair claim ordering: least-in-flight job first → round-robin effect, no starvation (DM-007). |
| Worker idle time | A worker idles only when *zero* eligible tasks exist system-wide; eager reduction keeps work flowing during the map phase; drain-mode fan-in shortens the tail. |

## 6. AWS deployment story

Same containers, same code; adapters (`BlobStore`, queue is Postgres in both) make
this a config change, not a rewrite.

```mermaid
flowchart LR
    subgraph AWS["AWS · single region"]
        ALB[ALB] --> APIS["ECS Fargate service: api\n(2+ tasks, stateless)"]
        APIS --> RDS[("RDS Postgres 16\nMulti-AZ")]
        WRK["ECS Fargate service: worker\ndesiredCount = W"] --> RDS
        WRK --> S3B[("S3 bucket")]
        APIS --> S3B
        SUPC["supervisor: sets ECS desiredCount\nfrom desired_workers + reaper"] --> RDS
        SUPC -->|UpdateService| WRK
    end
    U[User] --> ALB
```

- **W via API** becomes `ecs.updateService(desiredCount)` — the supervisor's reconcile
  loop is unchanged in shape (DM-008).
- RDS Multi-AZ gives control-plane HA; S3 gives 11-nines data durability; workers and
  API are cattle.
- **Deliberately NOT SQS in v1** — the eager-pairing step needs `{consume partials +
  create reduce task}` to be atomic; in Postgres that's one transaction, with SQS it's
  a dual-write requiring an outbox. At ~27k tasks/job and I/O-bound tasks, claim rate
  is «1k/s — far inside Postgres territory. The switch trigger (>5k tasks/s sustained,
  cross-service consumers) and the outbox migration are specified in DM-004.

## 7. Failure modes

| Failure | Detection | Recovery | Data at risk |
|---|---|---|---|
| Worker crash mid-task | lease expiry (reaper) | task → pending, re-claimed | none (idempotent keys) |
| Worker crash after PUT, before commit | lease expiry | retry overwrites same key | none |
| Duplicate execution (redelivery) | — | consumed-guard blocks double-consume of partials; PUTs idempotent | none |
| Poison task (bug, corrupt file) | attempts ≥ 3 | task → dead, job → failed with cause | job fails loudly, others unaffected |
| Reaper/supervisor down | health check | leases expire later; W drifts — degraded, not broken | none |
| Postgres down | connection errors | system pauses; workers back off; no partial state lost (A-6) | none |
| Object store down | GET/PUT errors | task-level retry w/ backoff | none |
| API down | ALB health | stateless → restart; jobs in flight unaffected (workers don't need API) | none |

## 8. What breaks first at 10× (evolution ladder)

1. **F → 1M**: tasks/job ≈ 270k — still fine in Postgres (indexed, «1k/s claims).
2. **Task rate > ~5k/s sustained** (many huge concurrent jobs, sub-second tasks):
   move queue to SQS + outbox (DM-004 failure condition). State stays in Postgres.
3. **C → 100M** (0.8 GB per vector): partials stop fitting the K×8 MB budget → chunk
   the C dimension *within* a task (stream in column blocks); topology unchanged.
4. **Workers → thousands**: Postgres connection pressure → PgBouncer, then the SQS move.
5. **Multi-tenant / quotas**: fairness ordering generalizes to weighted fair queuing
   (DM-007 evolution).

## 9. Security & ops notes (v1 scope)

No authn/authz (A-4); secrets via env/SSM; S3 bucket private with IAM task roles;
input values are synthetic (no PII). Metrics/events retained in `events` table; logs
to stdout → CloudWatch.

## 10. Document map

| Doc | Content |
|---|---|
| `01-requirements-and-assumptions.md` | FR/NFR, assumptions A-1…A-9, envelope |
| `03-lld.md` | schema DDL, claim SQL, transactions, worker loop, API spec, formats, class diagram |
| `itds/DM-001…DM-010` | one decision record per load-bearing choice |
