# Distributed Mean — Distributed Aggregation System

Design and working implementation for the "Distributed Mean" problem: compute the
index-wise mean of F files × C numbers across a fleet of W heterogeneous workers,
with a hard fan-in constraint of K=5 files per worker. The concrete setting is
**federated-learning weight aggregation** — the F inputs are model-weight vectors
that already exist on distributed nodes, submitted as `inputUris[]`; the system
ingests references and never generates data (`docs/00-problem-statement.md` §Setting).

## STATUS

**Design: complete. Implementation: complete and verified** — the full stack runs
under docker compose and a 23-test black-box suite passes against the live system,
including the brief's worked example ([1,2,3]+[4,5,6] → exactly [2.5, 3.5, 4.5]),
golden and property tests against a numpy oracle, a kill-a-worker chaos test with a
conservation assertion, a two-job fairness race, and a pinned two-connection proof
that pairing serialises.

## Run it

Prerequisites: Docker (with compose), Python 3.12+, make.

```bash
cd impl
make setup             # one-time: venv for the seed harness + tests
make up                # postgres, minio, api, 4 workers, supervisor, ui
make demo-example      # the brief's example → 2.5, 3.5, 4.5
make demo F=1000 C=100000   # a real job (~2–3 min at W=4)
make test              # the black-box suite against the live stack
make chaos             # kill a worker mid-job; the answer is still exact
```

Live views while a job runs: **http://localhost:3000/dashboard.html** (SSE dashboard —
workers free/busy, queue depth + stall gauges, per-job progress, event log) and
**http://localhost:8080** (API). Full runbook: `impl/README.md`.

## The thesis, in one sentence

Element-wise mean is a monoid fold, so workers exchange **(sum, count)** partials that
merge in any order; the 5-file RAM limit applies to partials too, forcing an eager
**5-ary reduction tree** through the queue; completion is the conservation proof that
a lone partial with **count = F** is the answer.

## How each critical aspect is answered

| Brief's criterion | Answer | Where |
|---|---|---|
| F > 5 ⇒ no 1:1 job↔queue-item | job explodes into map/reduce/finalize tasks on one queue | DM-001, HLD §3 |
| Efficient distribution | pull-based claiming + eager adaptive fan-in (straggler-proof) | DM-002 |
| Deciding a job is finished | conservation proof: lone partial with count=F | DM-003 |
| Multiple concurrent jobs | fairness = ORDER BY in the claim query (least-in-flight first) | DM-007 |
| **Bonus:** W via API | `PATCH /system/workers`; a supervisor reconciles the fleet | DM-008 |
| **Bonus:** live UI | events table + SSE; monotone coverage-based progress | DM-009 |

## If you have 15 minutes

`docs/04-decision-journey.md` (Scope + Bare minimum) → `docs/02-hld.md` §1–5 →
`docs/itds/DM-001`. Then the **[interactive simulator](https://ui-gray-theta.vercel.app/simulator.html)**
(also in-repo at `docs/simulator.html` / `impl/ui/simulator.html`) — it races the
chosen design against its rejected alternatives on identical seeds and worker speeds.

## Full reading order (docs/)

1. `00-problem-statement.md` — the brief, verbatim, with the federated-learning setting
2. `01-requirements-and-assumptions.md` — FR/NFR, assumptions A-1…A-10, envelope + service-time model
3. `04-decision-journey.md` — the decision index: question → chosen answer (one-line reasoning) → alternatives (one line each), tiered Scope → Bare minimum → MVP → Optimizations → Edge cases
4. `02-hld.md` — architecture, diagrams, why-not-Spark, failure modes, AWS story
5. `03-lld.md` — schema, claim SQL, the transactions, worker loop, API spec, runbook
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
| DM-011 | Build vs Spark/Dask/Temporal/Celery |

Supporting: `CONTEXT-BRIEF.md` (the locked-decision summary the documents share),
`research/` (prior art, comparative analysis, open derivation questions).

## Implementation layout (`impl/`)

| Directory | Contents |
|---|---|
| `api/` | Node 22 / Express / TypeScript: migrations (the schema source), job submission, REST + SSE |
| `worker/` | Python 3.12: claim → heartbeat(execute) → transactional commit + eager pairing |
| `supervisor/` | reaper (lease/deadline recovery + pairing trigger + backstop) and W reconciler |
| `harness/` | `seed.py` — plays the federated nodes: writes fixture inputs, submits jobs |
| `tests/` | the black-box suite (HTTP + DB + S3 assertions only) |
| `ui/` | static dashboard + simulator (no build step); deployed at ui-gray-theta.vercel.app |

## Production path

The same containers deploy to AWS unchanged in shape: ECS Fargate (api + worker
services), RDS Postgres Multi-AZ, S3, ALB; the supervisor's reconcile loop actuates
`ecs.updateService(desiredCount)` instead of the Docker API. Details and the
what-breaks-at-10× ladder: `docs/02-hld.md` §6–§8.
