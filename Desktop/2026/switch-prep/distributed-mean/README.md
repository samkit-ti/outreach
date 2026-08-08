# Distributed Mean — System Design Take-Home

Design + (upcoming) implementation for the "Distributed Mean" interview problem:
compute the index-wise mean of F files × C random numbers across a fleet of W
heterogeneous workers, with a hard fan-in constraint of K=5 files per worker.

## Current version: **v1** (design phase — iterating)

| Version | Date | Scope |
|---|---|---|
| v1 | 2026-08-09 | Initial full design: requirements, HLD, LLD, ITDs DM-001…DM-010 |

Each iteration copies `docs/vN/` → `docs/vN+1/` and edits there; older versions are
immutable history.

## Reading order

1. `docs/v1/00-problem-statement.md` — the prompt, verbatim
2. `docs/v1/01-requirements-and-assumptions.md` — FR/NFR, assumptions A-1…A-9, back-of-envelope
3. `docs/v1/02-hld.md` — architecture, diagrams, how each graded criterion is answered
4. `docs/v1/03-lld.md` — schema, transactions, claim SQL, worker loop, API spec, formats
5. `docs/v1/itds/` — one decision record per load-bearing choice:

| ITD | Decision |
|---|---|
| DM-001 | Aggregation topology: eager 5-ary reduction via the queue, (sum,count) partials |
| DM-002 | Work distribution & stragglers: pull-based + adaptive fan-in |
| DM-003 | Job completion: semantic (partial with count = F is the proof) |
| DM-004 | Queue: Postgres SKIP LOCKED (vs SQS/RabbitMQ/Redis), QueueAdapter + switch triggers |
| DM-005 | Data placement & formats: S3-API object store, CSV inputs, f64 binary partials |
| DM-006 | State model & failure handling: leases, at-least-once + idempotency |
| DM-007 | Multi-job fairness: round-robin via claim ordering, task-type priority |
| DM-008 | Worker pool & W configurability: supervisor reconciliation |
| DM-009 | Observability & UI: events table + SSE |
| DM-010 | Numerics: float64 + tree reduction (≈ pairwise summation) |

Supporting: `docs/v1/CONTEXT-BRIEF.md` (locked decisions D1–D12, canonical vocabulary),
`docs/v1/research/reading-list.md` (cited prior art).

## Planned (next phases)

- `impl/` — docker-compose demo: API (Node 22/Express/TS), Postgres 16, MinIO,
  Python 3.12 workers, supervisor, SSE UI
- `infra/` — AWS story (ECS Fargate + RDS + S3), per HLD §6

Tracked in beads: `outreach-zjth`.
