# Distributed Mean — Requirements & Assumptions

**Date:** 2026-08-10 · **Author:** Samkit Shah

---

## 1. Functional requirements

| ID | Requirement | Source |
|----|-------------|--------|
| FR-1 | User creates a job via API with parameters F (1 < F < 100k) — the length of the submitted `inputUris[]` — and C (1 < C < 1,000k). | prompt |
| FR-2 | The system accepts references to F **pre-existing** input files (`inputUris[]`, length F) holding C float64 values each, and reads them from an S3-API store. | prompt + setting (00) |
| FR-3 | The system computes `output[i] = mean(file_1[i] … file_F[i])` for every index i, producing one output file of C numbers. | prompt |
| FR-4 | Work is distributed over W system-level workers via a queue; workers idle until work appears. | prompt |
| FR-5 | When F > 5, the job must be split; one job may map to many queue items. | prompt |
| FR-6 | Partial worker outputs must be combined into the final averaged file. | prompt |
| FR-7 | Multiple jobs can be submitted and make progress concurrently. | prompt |
| FR-8 | User can fetch job status and the final result file. | implied |
| FR-9 | *(Bonus)* W is configurable via the API. | prompt |
| FR-10 | *(Bonus)* UI with live system state: workers free/busy, jobs completed, jobs queued, etc. | prompt |

## 2. Non-functional requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR-1 | **Worker RAM constraint:** a worker may hold at most K=5 files' worth of data at a time. Treated as a hard invariant, applied to partials too (a partial is file-shaped). | prompt |
| NFR-2 | **Heterogeneous workers:** workers process at different speeds; minimize idle/wait time. | prompt |
| NFR-3 | **Correctness:** result must equal the true index-wise mean (within float64 rounding); no mean-of-means bias. | derived |
| NFR-4 | **Fault tolerance:** a worker crash must not lose the job; tasks retry; no double-counting under retries. | derived — any fleet design must survive its own workers |
| NFR-5 | **Throughput over latency:** batch-analytics workload; optimize completion time of jobs, not per-request latency. | derived |
| NFR-6 | **Horizontal scalability of the data plane:** no single node may need to stream the whole dataset. | derived from envelope (800 GB max input) |
| NFR-7 | **Observability:** system state inspectable at any time (drives UI + operations). | bonus, promoted |

## 3. Explicit assumptions (stated because the brief is silent)

| ID | Assumption | Justification |
|----|-----------|---------------|
| A-1 | Values are float64 **model weights**, produced elsewhere — we do not choose their distribution or bounds. Trained weights are typically O(1); float64 gives ~2⁵³ of integer-exact headroom, so at F < 10⁵ the sum at any index stays far inside range for any realistic weight scale. | The no-overflow argument no longer rests on a bound we control: overflow would need per-value magnitudes ~10³⁰³, and the *precision* bound depends only on the number of addends, not their size. Stated honestly and argued in DM-010, whose Kahan-summation note is the escape hatch if weight magnitudes ever widen. |
| A-2 | Input files **pre-exist** at node-owned S3-API URIs and are read-only to us; the system never creates them. The demo seeds fixture files with a harness script (`make seed F=… C=…`) and then submits their URIs — a test harness, not a system feature. | The setting (00) is federated-learning aggregation: the weight vectors already sit on the nodes that trained them. Ingesting references is strictly less work and less trust than manufacturing 800 GB we would then read back. |
| A-3 | Jobs are one-shot and immutable; no cancel/update in the current scope (cancel is an evolution note). | Keeps state machine minimal; prompt doesn't ask for it. |
| A-4 | Single region, single tenant, no authn/authz in the current scope. | Current-scope simplification; noted in HLD §9. |
| A-5 | At-least-once task execution is acceptable if effects are idempotent. | Standard queue semantics; exactly-once is a myth across queue+storage boundaries. |
| A-6 | The DB (Postgres) is the availability floor: if it is down, the system pauses but does not corrupt. | Single-writer control plane is the simplest correct design at this scale; HA via RDS Multi-AZ on AWS. |
| A-7 | Worker count W is small-to-moderate: **1–32 (W_max, DM-008)**. | Bounded by the Postgres connection budget — 2 connections per worker (execute + heartbeat, LLD §5/§8) → 74 at W_max — and by the demo scope; documented switch triggers (PgBouncer, then SQS) if it grows. |
| A-8 | **K=5 is a logical fan-in limit on how many files' worth of data a task may have in flight; we honour the stricter byte reading too by streaming.** Every task type obeys it — there is no exempt type. | Canonical reading, quoted verbatim by DM-008. `map`/`reduce` stream inputs one at a time into a single length-C accumulator, so peak resident is ~1 vector (8 MB) not 5 (≈40 MB) — we satisfy both readings at once. |
| A-9 | Intermediate storage is plentiful (object store); we trade disk for parallelism. Intermediates are GC'd after job completion. | Object storage is cheap; ~F/4 partial objects worst case. |
| A-10 | Submitted `inputUris[]` are user-supplied and therefore untrusted: reads are permitted only for URIs on an allow-listed set of buckets/hosts (`INPUT_URI_ALLOWLIST`); our writes stay confined to `jobs/{jobId}/`. | The one place the setting adds attack surface the brief never had — an unrestricted fetcher is an SSRF primitive. HLD §9, LLD §6/§8. |

## 4. Back-of-envelope (drives every sizing decision)

Max job: F = 100k files, C = 1M values. The bounds in FR-1 are exclusive and the DDL enforces them as
`CHECK (f BETWEEN 2 AND 99999)` / `CHECK (c BETWEEN 2 AND 999999)`, so **true maxima are F=99,999,
C=999,999; the envelope is computed at the round F=10⁵ × C=10⁶ for arithmetic clarity — all figures
below are ≈1‰ overestimates.**

| Quantity | Value | Consequence |
|---|---|---|
| Total input | 10¹¹ numbers ≈ **800 GB** (f64), **read-only, never written by us** | No single node streams it all → distributed aggregation (NFR-6). |
| One file / partial | **8 MB** (f64 binary), ~20 MB CSV | Partials must live in the object store; queue messages carry URIs (SQS cap = 256 KB). |
| Map (leaf) tasks | ⌈100k/5⌉ = **20,000** | Task bookkeeping must be cheap → single indexed `tasks` table. |
| Reduce tasks | 20k→4k→800→160→32→7→2→1 ≈ **5,000**, 7 levels | Reduction is a real second phase, ~20% extra work; fan-in 5 keeps tree shallow (log₅). |
| Total tasks / max job | 20,000 `map` + ≈5,000 `reduce` + 1 `finalize` ≈ **25,000** | Even at W_max=32 and ~2.2 s/task → claim rate ≈14/s « 1k/s → Postgres queue comfortably in range (and it stays in range an order of magnitude above W_max). |
| Total data-plane **traffic** | ≈ **1.2 TB** per max job: 800 GB of input **reads** plus ≈400 GB of intermediates (≈200 GB partial writes — 25k × 8 MB, of which 160 GB is level 0 — and ≈200 GB read back one level up) | Data plane (S3/MinIO) does the heavy lifting; control plane stays tiny. The **intermediate writes (~200 GB)** are the only halvable component — see the cost row. |
| Peak **resident** bytes **we own** | ≈ **200 GB** per max job: the partial objects plus one result file | The 800 GB of inputs belongs to the nodes and is on their storage bill, not ours. Traffic and residency are different bills: traffic drives request/transfer cost, residency drives storage-days. Ours falls to ~0 after the completion GC. |
| Task payload size | < 1 KB (URIs + params) | Control plane rows are negligible next to data plane. |
| **Task service time** | **≈2.2 s** — the constant every wall-clock figure in this doc set uses | A `map` task moves 5 × ~20 MB CSV in + 8 MB f64 out ≈ 108 MB; at ~50 MB/s effective per-connection object-store throughput that is ≈2.2 s, and it is **I/O-bound, not CPU-bound** (the numpy add over 5M float64 is milliseconds). So one worker sustains **~0.45 tasks/s**, and claim rate is `W × 0.45` — ≈14/s at W_max=32, and still only ~90/s at a hypothetical 200 workers, three orders of magnitude inside the Postgres-queue band (DM-004). |
| Marginal cost, max job (AWS) | ≈ **$1–2** Fargate compute (~15.3 worker-hours at ~$0.05/vCPU-hr-class pricing) + ≈ **$4** S3 requests (~50k PUT/GET ops at $0.005/1k PUT, $0.0004/1k GET) + storage-days on the ~200 GB **resident** we own (not the 1.2 TB of traffic) | Compute is not the bill; **requests and intermediate bytes are**. The ~200 GB of intermediate writes is the halvable part — in-worker pre-combining (batch several map results before PUT) roughly halves both the byte count and the op count, and is exactly DM-001's failure condition 1. |

**Wall-clock model (uses the 2.2 s constant above, no other input).**

- **Demo job, F=1000 / C=100k:** 200 `map` + 63 `reduce` + 1 `finalize` = **264 tasks**
  ≈ 580 worker-seconds ≈ **2.4 min at W=4**. (The reduce chain over 200 leaf partials runs
  50 + 10 + 2 + 1 = **63** reduces across its levels, fan-in 5 in steady state with drain-mode
  fan-in in each level's tail. At C=100k the per-task bytes are 10× smaller, so 2.2 s is a
  conservative ceiling here — which is the right direction for a demo claim.)
- **Max job, F=100k / C=1M:** ≈25,000 tasks × 2.2 s ≈ **15.3 worker-hours** — so ≈**3.1 h at W=5**,
  ≈**29 min at W_max=32**. Linear in W, because the work is embarrassingly wide.
- **The floor W cannot remove:** the reduce tree is ~7 levels plus the leaf level, and a level-k partial
  cannot exist before its children, so **~8 serialised task latencies ≈ 18 s** remain no matter how many
  workers are added. Even at W_max=32 the max job is ~29 min, so the floor is invisible; on the F=8 demo
  job it *is* the runtime. This is the number that makes "add workers" stop working, and it is why DM-001 cares
  about tree depth rather than only about width.

Small-job sanity check (F=10, C=1000): 2 map tasks, 1 reduce, 1 finalize — the same machinery degenerates gracefully; no special-casing.

## 5. Out of scope (current iteration)

- Job cancellation, pause/resume, priorities set by users. **Cancellation has a designed escape hatch** and is the first planned addition: add `'cancelled'` to `job_status`, and because the claim query filters on job status (`j.status IN ('running','finalizing')`), setting it stops new claims immediately while in-flight tasks drain to completion on their own — no task killing, no lease games, no partial-cleanup pass beyond the lifecycle rule that already expires `partials/`. The design permits it; v1 simply does not expose it.
- **Input generation.** Inputs pre-exist at node-owned URIs (A-2); the system ingests references and never manufactures data. The demo's fixture seeder is a harness script, outside the system boundary.
- **Weighted aggregation (weighted FedAvg).** The mean is unweighted. Weighting clients by sample count is a one-line evolution — partials carry `(Σwᵢ·xᵢ, Σwᵢ)` instead of `(Σxᵢ, n)`, same monoid, same tree (DM-001, DM-010) — and is not built.
- AuthN/AuthZ, multi-tenancy, quotas.
- Cross-region, multi-cloud.
- Exactly-once semantics (replaced by idempotency, see DM-006).
- Autoscaling W on queue depth (bonus asks for *user-set* W; autoscaling documented as evolution in DM-008).

## 6. Success criteria for the deliverable

| Checkpoint | Target |
|---|---|
| Design doc set | HLD + LLD + 11 ITDs, internally consistent, every "critical aspect" from the brief traceable to a decision. |
| Demo | docker-compose up → submit F=1000/C=100k job + F=8 job concurrently → both complete; kill a worker mid-job → job still completes correctly; UI shows live state. |
| Correctness proof | Demo job result equals numpy single-node reference within 1e-9 relative error. |
| Straggler demo | Workers run with artificial speed factors (e.g. 1×/3×/10× slowdown); logs show fast workers doing proportionally more tasks and no worker idle while eligible tasks exist. |
