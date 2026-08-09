# CHANGELOG

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
