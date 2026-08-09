# ITD: DM-005 — Data Placement and Format

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001, DM-003, DM-004, DM-006, DM-007, DM-010, ../02-hld.md, ../CONTEXT-BRIEF.md

---

## Problem Statement

Two coupled questions: **where do the bytes live**, and **in what format**. A max job (F=100k, C=1M) means
**10¹¹ float64 ≈ 800 GB** of input (~1.9 TB as CSV), produced by distributed `generate` tasks (D9) and read
by ≈20,000 leaf `map` tasks. Each `map` and `reduce` task emits one **partial** — a vector of C partial
sums, **8 MB** as binary — and the ~7-level, fan-in-5 reduce tree pushes **≈200 GB of intermediate writes**
through the system (≈25k partials × 8 MB, of which the 20,000 level-0 leaf partials are 160 GB and the
reduce levels above add the remaining ~40 GB), plus **≈200 GB read** as each partial is consumed one level
up. So ~400 GB of intermediate data-plane traffic in total. No partial can travel
in a queue message (**SQS cap 256 KB**, 32,000× too small; see DM-004). So we need a store that a Node/TS
API and W Python workers can both write and read, addressed by URI in the queue and DB, with writes that are
**idempotent under at-least-once retry** (D7). Target: the same code path locally and on AWS, with no
coordination between writers.

---

## Context

- **The brief explicitly permits the easy answer:** "Generated files can be stored on the API's local
  filesystem or a place of our choosing (e.g. a bucket), as long as workers can pull/read them." So local-FS
  is a *sanctioned* option and must be rejected on real grounds, not dismissed.
- **Access pattern is write-once, read-once-or-twice, whole-object.** A `generate` task writes ~50 input
  files and never touches them again; a `map` task reads exactly 5 input files (K=5) end to end; a `reduce`
  task reads 2–5 partials end to end and writes one. **No partial reads, no updates, no appends, no random
  access, no rename-in-place** — the access pattern object storage is built for, which is why the classic
  object-store weaknesses (no in-place mutation, no cheap rename, listing semantics) cost us nothing.
- **Two languages must agree on the bytes.** The API (Node 22 / Express / TS) generates nothing itself but
  serves results and pre-signs URLs; **Python 3.12** workers do all reading and writing (D10). Any format
  must be cheap and dependency-light on *both* sides.
- **Concurrency and idempotency.** W workers write simultaneously to distinct keys, hundreds of tasks in
  flight across concurrent jobs. A completed write must become visible to every other node atomically — a
  `reduce` task must never observe a half-written partial — and because D7 is at-least-once, the store must
  make a second run of the same task harmless.
- **Interaction with DM-004:** the queue carries **references only** — `task_id`, `job_id`, and input/output
  URIs, a few hundred bytes. That is what keeps the queue choice independent of data volume.

---

## Alternatives — Data Placement

### API-local filesystem, shared to workers via a Docker volume

The API writes generated files under `/data/jobs/{jobId}/…`; the same host directory is bind-mounted into
every worker container. Partials are written to the same tree.

**Pros:**
- **Explicitly allowed by the brief** — zero justification burden, and it is the fastest thing to demo.
- Simplest possible code: `open()` / `read()`, no client library, no credentials, no extra container.
  `os.rename()` on the same filesystem is atomic, giving a free write-temp-then-rename idempotency story.
- Lowest latency and no network hop for local development; no S3 API semantics to learn.

**Cons:**
- **Single-writer coupling.** All 800 GB must transit the API host's filesystem and disk, turning a
  stateless HTTP tier into the storage bottleneck and a single point of failure, and breaking the "API is
  stateless" property the HLD relies on to scale replicas behind an ALB. It also drags back the D9 problem
  it was meant to avoid: if the API owns the filesystem, the pull to have the API generate all 100k files
  serially becomes strong.
- **No multi-node story and no AWS path.** A Docker bind mount is a single-host trick; the moment workers
  land on a second machine — the entire premise of "a fleet of workers" — the volume is gone. Fargate has no
  shared host directory, so adopting this locally means writing and testing a *second* storage backend for
  deployment.
- **No atomic multi-node visibility.** Local-FS `rename()` atomicity is a single-kernel property; over any
  network filesystem it is exactly what stops holding (see NFS below). The "never read a torn partial"
  invariant would be enforced by an accident of deployment rather than by the store.
- Doesn't scale past one disk: 800 GB is a provisioning decision, not an elastic one; no lifecycle expiry
  for the ~200 GB of dead intermediates.

### NFS / Amazon EFS shared filesystem

A POSIX filesystem mounted by every node; same `open()`/`read()` code, genuinely shared.

**Pros:**
- **Keeps POSIX semantics while being multi-node** — arguably the smallest change from the local-FS design
  that actually satisfies "a fleet of workers on many machines."
- Managed on AWS (EFS), so no self-hosted NFS server; elastic capacity, no pre-provisioning of the 800 GB.
  Directory listing is real and immediately consistent, nicer than object-store listing for debugging.

**Cons:**
- **`rename()` atomicity stops being something you can lean on.** NFS close-to-open consistency means a
  reader may serve cached attributes/data, so the write-temp-then-rename trick that is airtight on one
  kernel becomes client-cache-dependent across nodes — our core invariant would rest on mount options.
- **Metadata operations are the bottleneck.** 100k input files + ~25k partials in a handful of directories
  is a metadata-heavy workload, precisely NFS's weak spot; large directories degrade sharply.
- **Cost/throughput shape is wrong.** EFS Standard is roughly an order of magnitude dearer per GB-month than
  S3 Standard, with burst-credit/elastic throughput to tune for a ~200 GB burst — filesystem prices for
  object-store access patterns we never exploit.
- **Local dev needs an NFS container** — heavier and less faithful than MinIO, and mount privileges make it
  awkward in CI. Worse, the mount becomes a hard dependency of every container: a stuck mount hangs
  processes in uninterruptible sleep, so a wedged worker looks alive to the D7 lease while making no
  progress.

### S3-API object store (MinIO locally, Amazon S3 on AWS)

One `BlobStore` abstraction over the S3 API. `PUT` whole objects, `GET` whole objects, keys are strings. A
MinIO container in docker-compose locally; the identical client code points at Amazon S3 in deployment.

**Pros:**
- **Same code path locally and on AWS.** MinIO is S3-API-compatible, so the *only* difference between demo
  and deployment is an endpoint and credentials — no second backend, no shim. Local-FS cannot offer this;
  NFS offers it only partially.
- **Whole-object `PUT` is atomic and read-after-write consistent** (S3 has been strongly read-after-write
  consistent for all operations since December 2020). A reader sees either the complete old object or the
  complete new one, never a torn one — across nodes, guaranteed by the store rather than by mount options.
  Exactly the invariant `reduce` needs.
- **Idempotency falls out for free**: deterministic keys + atomic whole-object PUT means a retried task
  overwrites its own output byte-identically — no CAS, no temp-file dance, no locking (see the D7 tie-in
  below). And **no writer coordination**: thousands of concurrent PUTs to distinct keys need no agreement,
  because there is no shared mutable directory.
- **Elastic and cheap for this shape:** 800 GB is ~$18/month on S3 Standard, and **lifecycle rules expire
  `partials/` automatically** — reclaiming ~200 GB of dead intermediates without writing a garbage
  collector.
- **Pre-signed URLs** let the UI download the result directly, keeping the API off the data plane entirely.
  First-class clients both sides (`@aws-sdk/client-s3`, `boto3`).

**Cons:**
- **Higher per-operation latency than local disk** (tens of ms per GET vs sub-ms) — real, but amortised over
  8 MB whole-object transfers where throughput dominates and tasks already take seconds.
- **An extra container in the local demo** (MinIO) plus credentials/bucket bootstrap. MinIO is API-compatible,
  not bug-compatible, so the AWS path still deserves a smoke test.
- **No in-place mutation, no atomic rename, no cheap directory ops** — irrelevant here since we never mutate,
  rename or list on the hot path, but it would bite a different design.
- **Per-request cost and per-prefix rate ceilings** (~3,500 PUT / 5,500 GET per prefix per second); our
  `jobs/{jobId}/…` layout spreads across prefixes, so this is headroom, not a limit, at ≈25k tasks per job.

### Pass data through the DB (`bytea` / large objects) or inside queue messages

Store partials as `bytea` in Postgres, or inline the vector in the task message.

**Pros:**
- **One fewer system.** Partial bytes and the `partials` row commit in the *same* transaction — given how much
  DM-004 leans on transactional writes this is a genuinely coherent argument, not a straw man: it removes even
  the small window in which an object exists but its row doesn't.
- Backup, access control and lifecycle come from the DB we already run. For a toy job (F=10, C=1000) it is
  unambiguously the simplest thing that works.

**Cons:**
- **Queue-message variant dies on arithmetic.** A partial is **8 MB**; the SQS cap is **256 KB** — a **32×
  overshoot** per message, and ~32,000× the size of the reference (a few hundred bytes) we send instead.
  Even on a broker with a larger cap, ≈200 GB of intermediates through a queue abuses the medium; every
  broker's own guidance is the claim-check pattern, i.e. exactly what we do.
- **DB variant dies on volume.** 800 GB of input plus ~200 GB of intermediates in Postgres means TOAST-ing
  every 8 MB value with a WAL write for each (~2× write amplification) and a working set that evicts the
  buffer cache DM-004's claim query depends on. Backups grow from megabytes of metadata to a terabyte of
  throwaway vectors. (`bytea`'s hard 1 GB per-value limit isn't binding at 8 MB, but it signals the DB is
  not a data plane.)
- Streaming 8 MB blobs over the connection pool competes for the connections workers need for claims and
  heartbeats — the queue and the data plane would share one saturation point, coupling two failure domains
  we deliberately keep separate.

---

## Alternatives — Partial Format

The unit is a vector of **C float64 partial sums** (C up to 1,000k → **8 MB** binary). The `count` n does
**not** go in the payload: it lives in the `partials` row and is mirrored in object metadata, so format
choice is purely about the vector.

### CSV (one value per line)

**Pros:** human-readable, `cat`-able, greppable, identical to the input format so one reader serves both;
trivially diffable in tests.

**Cons:** **~20 MB vs 8 MB** — 2.5× the bytes, so ~2.5× the ≈200 GB of intermediate writes; text→float parse
and float→text format cost on **every** node of a ~7-level tree (the dominant CPU cost of an otherwise
trivial `sum`); and round-trip through decimal text risks precision loss unless every writer emits
`repr`-grade 17-significant-digit output — a correctness footgun the reduce tree would inherit (see DM-010).

### Raw little-endian float64 binary

A bare `C × 8` byte array, no header. `numpy.frombuffer(buf, dtype='<f8')` on the Python side; `Buffer` /
`DataView.getFloat64(offset, true)` on the TS side. Length is `len(buf) // 8`, and C is already known from
the job row.

**Pros:** **8 MB exactly**, the minimum without compression; **zero parse cost** — `frombuffer` is a zero-copy
view, so reading is memcpy-speed; bit-exact round-trip (no decimal conversion, so no precision question at
all); readable from both languages with **no third-party dependency**; corruption is trivially detectable
(`len(buf) % 8 != 0`, or a length mismatch against C).

**Cons:** **not self-describing** — endianness, dtype and length are conventions we must document and assert,
not properties of the file; opaque to `cat` (debugging needs `xxd`/`np.frombuffer`); a silent dtype or
endianness mistake produces plausible-looking garbage rather than an error, so it needs an explicit assertion
at read time; no built-in checksum.

### `.npy` (numpy's own serialization format)

**Pros:** self-describing (dtype, shape, byte order in the header), so the file carries its own contract;
one-line `np.load` / `np.save`; still binary, so within a few hundred bytes of raw in size; standard and
versioned.

**Cons:** **numpy-specific framing.** The Node side would have to **reimplement the `.npy` header parser**
(magic string, version, ASCII dict of `descr`/`fortran_order`/`shape`, padding rules) — a hand-written parser
for another ecosystem's format, precisely the cross-language liability we rejected in DM-004 for queue
libraries. And the self-description buys nothing here: dtype and length are fixed by design and C is already
in the job row, so we'd pay the parser to be told what we already know.

### Parquet

**Pros:** columnar with built-in compression (float64 in [0,1) would shrink meaningfully), embedded schema and
statistics, checksums, and a rich ecosystem — if these vectors ever needed analytical querying (Athena,
DuckDB, Spark) this would be the answer.

**Cons:** **columnar overkill for a flat single-column vector** — we always read 100% of every value exactly
once, the one access pattern columnar layout does not help; row-group and metadata machinery for a single
column of C values is pure overhead; requires a heavy dependency on both sides (`pyarrow` ~100 MB, and
`parquetjs`-class libraries on Node are markedly less mature); encode/decode CPU on every level of a ~7-level
tree in exchange for bytes we are not short of; and compression works against the zero-copy read that makes
raw binary free.

---

## Chosen: S3-API object store everywhere; CSV inputs, raw float64 partials, CSV result

**Decision.** One `BlobStore` abstraction over the **S3 API**: **MinIO** container in docker-compose
locally, **Amazon S3** on AWS, identical client code. The queue and DB carry **URIs only** (DM-004). **Input
files: CSV**, one value per line. **Partials: raw little-endian float64 binary** (`count` in the `partials`
row and object metadata). **Result: CSV**, mirroring the input format.

**Key layout:**

```
jobs/{jobId}/inputs/{fileIdx}.csv     # one value per line, uniform [0,1)
jobs/{jobId}/partials/{taskId}.f64                # C × little-endian float64, no header
jobs/{jobId}/result.csv                           # C means, one per line
```

**Positive case.**

1. **One data plane, two environments, zero divergence.** The S3 API is the only choice that is both a real
   distributed store *and* runnable in a container, so the demo exercises the same code as the deployment.
   We never write, and never have to trust, a second backend.
2. **Idempotent writes fall out of the key layout — this is the tie to D7.** The key is derived
   **deterministically from the task id** (`jobs/{jobId}/partials/{taskId}.f64`) and a whole-object `PUT` is
   atomic. So a task redelivered under at-least-once (lease expiry, crash after PUT but before DB commit,
   duplicate delivery) recomputes the **same** vector from the **same** inputs and PUTs it to the **same**
   key: a harmless byte-identical overwrite. No locks, no CAS, no temp-and-rename, no "did my predecessor
   finish" check — last-writer-wins is a no-op when every writer writes identical bytes. D7's idempotency is
   therefore not extra machinery; it is a property of naming objects after tasks. It also removes the need
   for a distributed transaction across store and DB: **PUT first, then commit** — a crash in between leaves
   an orphan object the retry overwrites and lifecycle expiry collects.
3. **Format is chosen to make the interior of the tree free.** Partials are written and read at every one of
   ~7 levels; only leaves read input and only `finalize` writes the result, so the format that matters is
   the partial format. Raw float64 makes it **8 MB instead of ~20 MB** (≈200 GB of intermediate writes
   instead of ~500 GB) with **zero parse cost** — `np.frombuffer` is a zero-copy view and summing 5 such
   views is one vectorised add. Meanwhile CSV survives exactly where humans look: inputs (so `head` shows
   the data) and the result (so the answer is checkable by eye against the brief's `[1,2,3] + [4,5,6] →
   [2.5,3.5,4.5]` example). The asymmetry is deliberate: readability at the boundaries, efficiency in the
   interior.
4. **Both languages read it with no dependency.** Python `np.frombuffer(buf, dtype='<f8')`; TypeScript `new
   DataView(buf).getFloat64(i * 8, true)`. Little-endian is not a compromise — it is native on x86-64 and
   arm64, so there is no byte-swap anywhere.
5. **The store does the garbage collection.** A lifecycle rule expiring `jobs/*/partials/` reclaims the ~200
   GB of dead intermediates with a config line instead of a GC service.

**Result delivery.** This ITD owns the decision, because "who moves the result bytes" is a data-placement
question and the answer has to be consistent with the thesis above — the API is not on the data plane.
`GET /jobs/:id/result` returns **302 to a 15-minute pre-signed GET URL** for
`jobs/{jobId}/result.csv`, so the client fetches the object directly from S3/MinIO and no result byte ever
transits the Node process. For curl and demo ergonomics, `?inline=1` makes the API proxy the stream
instead — an explicit opt-in for a C=1000 toy result, never the path a real consumer takes at C=1M
(8 MB of CSV per download through a stateless tier that must scale on request count, not bandwidth).
Before the job reaches `completed` the endpoint returns **409** with the job's current status rather than
a redirect to a non-existent object. Completion is discovered by the caller either from the
`job.completed` SSE event on `GET /events` (DM-009) or by polling `GET /jobs/:id`; **webhooks are out of
scope** — there is no authenticated caller today to sign a callback to, so a webhook would be an
unauthenticated POST to a client-supplied URL, i.e. an SSRF primitive rather than a feature.

**Why each alternative was rejected, specifically.**
- **API-local filesystem + Docker volume** — rejected despite being explicitly permitted, on three
  specifics: **single-writer coupling** (800 GB through a node that must stay stateless and horizontally
  scalable), **no AWS story** (Fargate has no shared host directory, so we'd build and test a second backend
  anyway), and **no atomic multi-node visibility** (local-FS `rename` atomicity is single-kernel, so the
  "never read a torn partial" invariant would hold by deployment accident). It answers the demo and declines
  the design question.
- **NFS / EFS** — genuinely multi-node, but close-to-open consistency downgrades `rename()`-based atomicity
  to a mount-option property; metadata cost dominates with 100k files + ~25k partials; EFS is ~10× S3's
  per-GB price for POSIX semantics we never use; and a wedged mount produces a worker that looks alive to
  the D7 lease while making no progress. Filesystem prices and filesystem risks for object-store behaviour.
- **DB (`bytea`) or in-message data** — the in-message variant is arithmetically dead (**8 MB vs SQS's 256
  KB cap** = 32× overshoot per message, ≈200 GB through a broker in aggregate; claim-check is the documented
  answer). The `bytea` variant passes the size check but not the volume one: ~200 GB of TOAST-ed values with
  WAL amplification would evict the buffer cache DM-004's claim query depends on and couple queue and data
  plane into one saturation point. Its one real merit — bytes and row in one transaction — is neutralised by
  deterministic keys: PUT-then-commit is already safe, so we never needed the atomicity we'd be paying for.
- **CSV partials** — 2.5× the bytes and a parse/format round-trip at every tree level, plus a
  decimal-precision footgun that would propagate through the reduce tree (DM-010). Its readability is only
  valuable at the boundaries, which is where we already keep CSV.
- **`.npy`** — self-description is its only advantage and it is worthless here (dtype and length are fixed
  by design; C is in the job row) while its cost is real: the Node side must hand-reimplement numpy's header
  format. Paying a cross-language parser to learn what we already know.
- **Parquet** — columnar layout, compression and statistics optimise selective/analytical reads; we do
  full-vector sequential reads exactly once. It adds `pyarrow`-class dependencies on both sides (with a
  notably weaker Node story), encode/decode CPU at every tree level, and defeats the zero-copy read. Right
  answer if partials became a queryable dataset; wrong answer for a flat vector consumed once.

**Failure condition — what would make us revisit.**
- **C raised above ~10⁸** (single vector > ~800 MB): a partial no longer fits comfortably in worker RAM,
  forcing **chunked partials** — range keys (`partials/{taskId}/{chunkIdx}.f64`), multipart upload, ranged
  GETs, chunk-aware reduce. Raw binary actually *helps* here (byte offsets map exactly to element offsets,
  `chunk_bytes = n_elems × 8`), but the key layout and reduce loop both change.
- **Partials become an analytical dataset** — if intermediates must be queried (cross-job comparison, drift
  analysis, audit retention), Parquet's schema/statistics/compression start paying for themselves and raw
  binary becomes a liability.
- **Object-store latency exceeds ~30% of mean task service time** — e.g. many small-C jobs where 8 MB
  shrinks to kilobytes and per-request overhead dominates: add a node-local read-through cache for inputs,
  or batch small partials into one object per reduce group.
- **Intermediate traffic grows well past ~200 GB written per job** (deeper trees, wider fan-out): compress partials
  with zstd (trading the zero-copy read for bytes), or keep same-node reduce chains on local scratch and
  publish only tree-level boundaries.
- **Cross-region workers** (same trigger as DM-004): cross-region GETs make transfer cost and latency
  dominate, pushing toward per-region buckets with replication and region-affine task placement.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Partial size | Exactly `C × 8` bytes; 8,000,000 B at C=1M (vs ~20 MB CSV) | `HeadObject` content-length assertion in an integration test |
| Cross-language round-trip | Bit-exact: bytes written by Python `np.tofile` read back by TS `DataView` and re-read by Python compare identical | Round-trip test in CI over random vectors incl. denormals, 0.0, values near 1.0 |
| Idempotent overwrite | Re-running a completed `map`/`reduce` task produces a byte-identical object; final result unchanged | Force-replay 100 done tasks; `sha256` the object before/after; assert equal |
| No torn reads | 0 short/torn partial reads across 10k concurrent PUT/GET pairs | Reader asserts `len(buf) == C × 8` on every GET; count failures over a soak |
| Same code path | 0 storage-backend conditionals; MinIO→S3 switch is endpoint + credentials only | `grep` for backend branching in `BlobStore`; run the same suite against MinIO and S3 |
| Parse cost | Partial deserialisation < 1% of task wall time | Per-task timing split: GET, deserialise, compute, PUT |
| Intermediate volume | ≈200 GB written per max job (25k partials × 8 MB; 160 GB of it level-0 leaves), ≈200 GB read back | Sum of PUT content-lengths from the `events` table (D11) per job |
| API off the data plane | 0 bytes of input or partial data transit the API process | Result served by pre-signed URL; assert API egress ≈ metadata only |
