# Distributed Mean — System Design Take-Home

Design + (upcoming) implementation for the "Distributed Mean" interview problem:
compute the index-wise mean of F files × C random numbers across a fleet of W
heterogeneous workers, with a hard fan-in constraint of K=5 files per worker.

## STATUS

**Design: complete and adversarially reviewed (v2). Implementation: not started —
next phase.** Every "Success Metrics" table in the ITDs is an *acceptance target for
the implementation*, not a measurement; numeric projections derive from the envelope
in `01 §4`. The first code to be written (highest proof-value first): the T2
eager-pairing transaction + claim query with a two-connection concurrency test,
then the worker loop, then the API.

## The thesis, in one sentence

Element-wise mean is a monoid fold, so workers exchange **(sum, count)** partials that
merge in any order; the 5-file RAM limit applies to partials too, forcing an eager
**5-ary reduction tree** through the queue; completion is the conservation proof that
a lone partial with **count = F** is the answer.

## How each graded criterion is answered

| Interviewer's criterion | Answer | Where |
|---|---|---|
| F > 5 ⇒ no 1:1 job↔queue-item | job explodes into generate/map/reduce/finalize tasks on one queue | DM-001, HLD §3 |
| Efficient distribution | pull-based claiming + eager adaptive fan-in (straggler-proof) | DM-002 |
| Deciding a job is finished | conservation proof: lone partial with count=F | DM-003 |
| Multiple concurrent jobs | fairness = ORDER BY in the claim query (least-in-flight first) | DM-007 |
| **Bonus:** W via API | supervisor reconciles `desired_workers` (compose scale / ECS desiredCount) | DM-008 |
| **Bonus:** live UI | events table + SSE; monotone coverage-based progress | DM-009 |

## If you have 15 minutes

`docs/v2/02-hld.md` §1–5 → `docs/v2/itds/DM-001` → `DM-003`. Then the
**[interactive simulator](https://claude.ai/code/artifact/ee9896b4-7e99-4aeb-b378-33290d2acd41)** —
race the chosen design against its rejected alternatives (same seed, same workers).

## Current version: **v2** (see `docs/v2/CHANGELOG.md`)

| Version | Date | Scope |
|---|---|---|
| v2 | 2026-08-10 | Hardened after two adversarial review passes: 4 blockers fixed (claim-query `finalizing` hole, pairing mutual-decline race → per-job advisory lock, heartbeat fencing, priority inversion), result delivery decided, admission control, API idempotency, DM-011 added, numerics claim made honest. 44 findings triaged. |
| v1 | 2026-08-09 | Initial full design: requirements, HLD, LLD, ITDs DM-001…DM-010, journey, simulator. Immutable. |

## Full reading order (docs/v2/)

1. `00-problem-statement.md` — the prompt, verbatim
2. `01-requirements-and-assumptions.md` — FR/NFR, assumptions A-1…A-9, envelope + service-time model
3. `02-hld.md` — architecture, diagrams, why-not-Spark, failure modes, AWS story
4. `03-lld.md` — schema, claim SQL, the three transactions, worker loop, API spec, runbook
5. `04-decision-journey.md` — the incremental derivation: 14 steps, each with its proof and refs
6. `itds/` — one decision record per load-bearing choice:

| ITD | Decision |
|---|---|
| DM-001 | Aggregation topology: eager 5-ary reduction, (sum,count) partials |
| DM-002 | Work distribution & stragglers: pull + adaptive fan-in (advisory-lock pairing) |
| DM-003 | Job completion: data proof (count=F) + liveness predicate |
| DM-004 | Queue: Postgres SKIP LOCKED vs SQS/RabbitMQ/Redis, switch triggers |
| DM-005 | Data placement & formats; result delivery via pre-signed URL |
| DM-006 | State model & failure handling: leases, fencing, idempotency, task deadline |
| DM-007 | Multi-job fairness: least-in-flight claim ordering |
| DM-008 | Worker pool & W-via-API: supervisor reconciliation *(bonus 1)* |
| DM-009 | Observability & UI: events + SSE, monotone progress *(bonus 2)* |
| DM-010 | Numerics: float64 + tree; accuracy-neutral vs numpy |
| DM-011 | Build vs Spark/Dask/Temporal/Celery *(v2)* |

Supporting: `CONTEXT-BRIEF.md` (locked decisions D1–D12 — internal scaffolding, strip
on export), `research/reading-list.md`, `simulator.html` (source of the published
artifact), `CHANGELOG.md`.

> **Note for export:** if this tree is submitted as the take-home, drop
> `CONTEXT-BRIEF.md`, `itds/TEMPLATE.md`, `CHANGELOG.md`, the `**Simulation:**` link
> lines in DM-001/002/003/006/007, and this note; they are working scaffolding and
> private tool links.

## Planned (next phase — tracked in beads: `outreach-zjth`)

- `impl/` — docker-compose demo: API (Node 22/Express/TS), Postgres 16, MinIO,
  Python 3.12 workers, supervisor, SSE UI; chaos + straggler + fairness demos per LLD §10
- `infra/` — AWS deployment (ECS Fargate + RDS + S3), per HLD §6
