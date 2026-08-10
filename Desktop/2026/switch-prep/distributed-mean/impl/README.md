# Distributed Mean — Implementation

The working system per `../docs/` (LLD is the contract): Node 22/Express/TS API,
Postgres 16 (state + queue), MinIO (S3 API), Python 3.12 workers, supervisor
(reaper + W reconciler), static SSE dashboard + design-lab simulator.

## Quick start

```bash
cd impl
make up                # build + start: postgres, minio, api, 4 workers, supervisor, ui
make demo-example      # the brief's example: [1,2,3]+[4,5,6] → 2.5, 3.5, 4.5
make demo F=1000 C=100000   # the standard demo job (~2–3 min at W=4)
make test              # 23-test black-box suite against the live stack
make chaos             # kill a worker mid-job; the answer is still exact
make down              # stop; `make clean` also drops volumes
```

| Where | What |
|---|---|
| http://localhost:3000 | UI: landing → dashboard (live SSE) + simulator |
| http://localhost:8080 | API (`/healthz`, `/jobs`, `/system/stats`, `/events`) |
| http://localhost:9001 | MinIO console (dmadmin / dmsecret) |
| localhost:5433 | Postgres (dm / dm / dm) |

## Layout

```
api/          TS API: migrations (the schema source), T1 submit, REST + SSE
worker/       Python worker: claim → heartbeat(execute) → T2 commit+pairing / T4
supervisor/   reaper (T3 + pairing trigger + backstop) + Docker W reconciler
harness/      seed.py — fixture "nodes": PUTs input files, optionally submits
tests/        black-box pytest suite (HTTP + DB + S3 assertions only)
ui/           static pages (no build step); vercel.json for `vercel deploy`
```

## Notes

- Inputs are **pre-existing** objects at allow-listed S3 URIs (`INPUT_URI_ALLOWLIST`);
  the harness plays the role of the federated nodes.
- Change W at runtime: `curl -X PATCH localhost:8080/system/workers -H 'content-type: application/json' -d '{"desired": 8}'` —
  the supervisor converges the fleet (0–32).
- Straggler demo: `make straggler` adds a worker with `SPEED_FACTOR=10`; watch
  the dashboard — the slow worker's blast radius is one task at a time.
- Pre-signed result URLs are signed against `S3_PUBLIC_ENDPOINT` (host-reachable);
  on AWS it equals `S3_ENDPOINT` and the distinction disappears.
