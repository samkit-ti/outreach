# ITD: DM-005 — Data Placement and Format

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001, DM-003, DM-004, DM-006, DM-007, DM-010, ../02-hld.md, ../CONTEXT-BRIEF.md

---

## Problem Statement

Two coupled questions: **where do the bytes live**, and **in what format**. A max job (F=100k, C=1M) means
**10¹¹ float64 ≈ 800 GB** of input (~1.9 TB where a node holds CSV) — F model-weight vectors that **already
exist on distributed nodes**, exposed at S3-API URIs the caller supplies with the job and read, whole and
read-only, by ≈20,000 leaf `map` tasks. We never produce an input byte and never write one. Each `map` and
`reduce` task emits one **partial** — a vector of C partial
sums, **8 MB** as binary — and the ~7-level, fan-in-5 reduce tree pushes **≈200 GB of intermediate writes**
through the system (≈25k partials × 8 MB, of which the 20,000 level-0 leaf partials are 160 GB and the
reduce levels above add the remaining ~40 GB), plus **≈200 GB read** as each partial is consumed one level
up. So ~400 GB of intermediate traffic on top of 800 GB of input reads: **≈1.2 TB of data-plane traffic**
per max job, of which the **≈200 GB of intermediates plus the result is the only part we own** — the inputs
belong to the nodes. No partial can travel
in a queue message (**SQS cap 256 KB**, 32,000× too small; see DM-004). So we need a store that a Node/TS
API and W Python workers can both write and read, addressed by URI in the queue and DB, with writes that are
**idempotent under at-least-once retry** (D7), and a read path that can reach objects we do not own without
becoming a way to reach objects nobody should. Target: the same code path locally and on AWS, with no
coordination between writers.

---

## Context

- **The brief's permission is about files we place, and the inputs are not ours to place.** It allows that
  "Generated files can be stored on the API's local filesystem or a place of our choosing (e.g. a bucket), as
  long as workers can pull/read them" — a sanctioned local-FS option that must be rejected on real grounds,
  not dismissed. But in this setting the input vectors already live on the nodes that own them; there is no
  step at which we could put them anywhere, so the API-local-filesystem option is simply unavailable *for
  inputs*. The question narrows to where **our** bytes live — the ~200 GB of intermediate partials and the
  result — plus how workers reach input URIs they do not own.
- **Access pattern is write-once, read-once-or-twice, whole-object.** Each input object is read whole, once,
  by exactly one `map` task; a `map` task reads ≤5 whole input objects (K=5) end to end and writes one
  partial; a `reduce` task reads 2–5 partials end to end and writes one. **No partial reads, no updates, no
  appends, no random access, no rename-in-place** — the access pattern object storage is built for, which is
  why the classic object-store weaknesses (no in-place mutation, no cheap rename, listing semantics) cost us
  nothing.
- **Two languages must agree on the bytes.** The API (Node 22 / Express / TS) never touches the data plane —
  it validates `inputUris`, serves results and pre-signs URLs; **Python 3.12** workers do all reading and
  writing (D10). Any format must be cheap and dependency-light on *both* sides.
- **Concurrency and idempotency.** W workers write simultaneously to distinct keys, hundreds of tasks in
  flight across concurrent jobs. A completed write must become visible to every other node atomically — a
  `reduce` task must never observe a half-written partial — and because D7 is at-least-once, the store must
  make a second run of the same task harmless.
- **Interaction with DM-004:** the queue carries **references only** — `task_id`, `job_id`, and input/output
  URIs, a few hundred bytes. That is what keeps the queue choice independent of data volume.
- **The read side is now caller-controlled, so it is an attack surface.** `POST /jobs` accepts an explicit
  `inputUris[]`; a URI a client can name is a URI a worker will fetch, which is the shape of an SSRF
  primitive. The store choice has to leave room for a read allow-list, not just a write confinement.

---

## Alternatives — Data Placement

### API-local filesystem, shared to workers via a Docker volume

Our bytes live under `/data/jobs/{jobId}/…` on the API host; the same host directory is bind-mounted into
every worker container. Partials and results are written to that tree.

**Pros:**
- **The closest thing to what the brief explicitly allows** — low justification burden, and it is the
  fastest thing to demo.
- Simplest possible code: `open()` / `read()`, no client library, no credentials, no extra container.
  `os.rename()` on the same filesystem is atomic, giving a free write-temp-then-rename idempotency story.
- Lowest latency and no network hop for local development; no S3 API semantics to learn.

**Cons:**
- **It cannot reach the inputs at all.** The 800 GB we must read lives on other nodes behind S3-API URIs. A
  bind-mounted host directory is not a way to read them, so this option covers at most half the data plane
  and a blob client has to exist anyway — at which point the filesystem is a second, redundant backend
  rather than a simplification.
- **Single-writer coupling.** All ~200 GB of intermediates would transit the API host's filesystem and disk,
  turning a stateless HTTP tier into the storage bottleneck and a single point of failure, and breaking the
  "API is stateless" property the HLD relies on to scale replicas behind an ALB.
- **No multi-node story and no AWS path.** A Docker bind mount is a single-host trick; the moment workers
  land on a second machine — the entire premise of "a fleet of workers" — the volume is gone. Fargate has no
  shared host directory, so adopting this locally means writing and testing a *second* storage backend for
  deployment.
- **No atomic multi-node visibility.** Local-FS `rename()` atomicity is a single-kernel property; over any
  network filesystem it is exactly what stops holding (see NFS below). The "never read a torn partial"
  invariant would be enforced by an accident of deployment rather than by the store.
- Doesn't scale past one disk: ~200 GB of concurrent intermediates is a provisioning decision, not an elastic
  one, and there is no lifecycle expiry to reclaim them once the job is done.

### NFS / Amazon EFS shared filesystem

A POSIX filesystem mounted by every node; same `open()`/`read()` code, genuinely shared.

**Pros:**
- **Keeps POSIX semantics while being multi-node** — arguably the smallest change from the local-FS design
  that actually satisfies "a fleet of workers on many machines."
- Managed on AWS (EFS), so no self-hosted NFS server; elastic capacity, no pre-provisioning of the ~200 GB.
  Directory listing is real and immediately consistent, nicer than object-store listing for debugging.

**Cons:**
- **It still does not reach the inputs.** Mounting a shared filesystem across our fleet says nothing about
  100k vectors that live on nodes we do not administer, so a blob client remains mandatory and the mount is
  an extra backend beside it rather than instead of it.
- **`rename()` atomicity stops being something you can lean on.** NFS close-to-open consistency means a
  reader may serve cached attributes/data, so the write-temp-then-rename trick that is airtight on one
  kernel becomes client-cache-dependent across nodes — our core invariant would rest on mount options.
- **Metadata operations are the bottleneck.** ≈25k partials in a handful of directories per job, across
  concurrent jobs, is a metadata-heavy workload, precisely NFS's weak spot; large directories degrade sharply.
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
- **It is the protocol the inputs are already spoken in.** The nodes expose their vectors at S3-API URIs, so
  one client reads foreign inputs and reads/writes our own intermediates — one abstraction for the whole data
  plane rather than a blob client plus a filesystem.
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
- **Elastic and cheap for this shape:** the ~200 GB we actually own is ~$5/month on S3 Standard, and
  **lifecycle rules expire `partials/` automatically** — reclaiming the dead intermediates without writing a
  garbage collector.
- **Read scope is expressible as policy, not as code.** Because reads are just `GET`s against named
  buckets/hosts, restricting which URIs a worker may fetch is a config list plus an IAM boundary, which is
  what makes accepting caller-supplied `inputUris` defensible at all.
- **Pre-signed URLs** let the UI download the result directly, keeping the API off the data plane entirely.
  First-class clients both sides (`@aws-sdk/client-s3`, `boto3`).

**Cons:**
- **Higher per-operation latency than local disk** (tens of ms per GET vs sub-ms) — real, but amortised over
  8 MB whole-object transfers where throughput dominates and tasks already take seconds.
- **An extra container in the local demo** (MinIO) plus credentials/bucket bootstrap, and — since the system
  never produces inputs — a **fixture harness** to stand in for the nodes: `make seed F=… C=…` writes fixture
  vectors into MinIO and then submits a job with those URIs. That is test scaffolding outside the service, not
  a system feature, but it is real setup cost. MinIO is API-compatible, not bug-compatible, so the AWS path
  still deserves a smoke test.
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
- **DB variant dies on volume.** ~200 GB of intermediates per max job in Postgres means TOAST-ing
  every 8 MB value with a WAL write for each (~2× write amplification) and a working set that evicts the
  buffer cache DM-004's claim query depends on. Backups grow from megabytes of metadata to hundreds of
  gigabytes of throwaway vectors. (`bytea`'s hard 1 GB per-value limit isn't binding at 8 MB, but it signals
  the DB is not a data plane.) And it does nothing about the input side, which is not ours to store at all.
- Streaming 8 MB blobs over the connection pool competes for the connections workers need for claims and
  heartbeats — the queue and the data plane would share one saturation point, coupling two failure domains
  we deliberately keep separate.

---

## Alternatives — Partial Format

The unit is a vector of **C float64 partial sums** (C up to 1,000k → **8 MB** binary). The `count` n does
**not** go in the payload: it lives in the `partials` row and is mirrored in object metadata, so format
choice is purely about the vector.

### CSV (one value per line)

**Pros:** human-readable, `cat`-able, greppable, identical to one of the input formats we already accept so
one reader serves both; trivially diffable in tests.

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

**Pros:** columnar with built-in compression (narrowly-distributed weight values would shrink somewhat),
embedded schema and statistics, checksums, and a rich ecosystem — if these vectors ever needed analytical
querying (Athena, DuckDB, Spark) this would be the answer.

**Cons:** **columnar overkill for a flat single-column vector** — we always read 100% of every value exactly
once, the one access pattern columnar layout does not help; row-group and metadata machinery for a single
column of C values is pure overhead; requires a heavy dependency on both sides (`pyarrow` ~100 MB, and
`parquetjs`-class libraries on Node are markedly less mature); encode/decode CPU on every level of a ~7-level
tree in exchange for bytes we are not short of; and compression works against the zero-copy read that makes
raw binary free.

---

## Input Format — What We Accept, Not What We Choose

The partial format is a design choice; the **input** format is not. The vectors already exist on the nodes
in whatever encoding those nodes hold, so the only decision available is **what we agree to read**. We accept
two encodings and no others:

- **CSV** — one float64 value per line, `C` lines. What a node holding human-inspectable weights will have.
- **Raw little-endian float64** (`.f64`) — a bare `C × 8` byte array, no header. What a node that dumped a
  tensor will have.

Dispatch is by **file extension** (`.csv` → text reader, `.f64` → `np.frombuffer(buf, dtype='<f8')`), because
the extension is information the caller already gave us in the URI and content sniffing on an 8 MB object
means reading it twice or guessing from a prefix. An unrecognised extension is a validation error at read
time, not a guess.

**Both are validated against the declared `C`** before a single value is summed: for `.f64`, `len(buf) ==
C × 8` (and `len(buf) % 8 == 0`); for CSV, the parsed row count equals `C`. A mismatch is a **permanent**
error — no retry can change the length of an object — so it is recorded as such and the task consumes its
attempts and dies rather than pretending (DM-006). This check is the whole reason a headerless binary format
is safe on the input side too: `C` comes from the job row, so the length assertion is a real contract, not a
convention.

The other two formats stay as chosen below: **partials are raw little-endian float64** (interior of the
tree, never read by a human), and the **result is CSV** (the one artefact a human checks by eye).

---

## Chosen: S3-API object store everywhere; CSV-or-`.f64` inputs, raw float64 partials, CSV result

**Decision.** One `BlobStore` abstraction over the **S3 API**: **MinIO** container in docker-compose
locally, **Amazon S3** on AWS, identical client code. The queue and DB carry **URIs only** (DM-004). **Input
files: caller-supplied URIs, CSV or raw `.f64`, sniffed by extension and length-checked against C.**
**Partials: raw little-endian float64 binary** (`count` in the `partials` row and object metadata).
**Result: CSV**, so the answer is readable.

**Key layout.** Only the second and third lines are keys *we* mint; the inputs are external:

```
s3://<allow-listed node bucket>/<node's own key>   # F model-weight vectors, .csv or .f64 — read-only, not ours
jobs/{jobId}/partials/{taskId}.f64                 # C × little-endian float64, no header
jobs/{jobId}/result.csv                            # C means, one per line
```

Input URIs obey no layout of ours: they arrive in `inputUris[]` at submission, they may point at different
buckets on different hosts, and a `map` task's payload carries the ≤5 it must read. Our bucket contains
**only** `jobs/{jobId}/partials/…` and `jobs/{jobId}/result.csv`.

**Read allow-list and write confinement.** Because the read set is caller-supplied, the two directions get
different guards. `BlobStore` **writes** stay confined to the calling job's `jobs/{jobId}/` prefix, as
before — a task cannot write outside its own job, so a bug cannot corrupt a sibling's partials. `BlobStore`
**reads** are permitted only for URIs whose bucket/host appears in `INPUT_URI_ALLOWLIST` (config), enforced
twice: at `POST /jobs` so a bad URI is a 400 at submission rather than a dead task hours later, and again in
the worker's `BlobStore` so the queue cannot become a bypass. Without this, `inputUris[]` is an SSRF
primitive — an unauthenticated caller naming an internal endpoint and having a worker fetch it — which is the
same reason webhooks are out of scope below. The worker's IAM role is likewise read-only outside its own
bucket.

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
   views is one vectorised add. Meanwhile CSV survives exactly where humans look: at the result (so the
   answer is checkable by eye against the brief's `[1,2,3] + [4,5,6] → [2.5,3.5,4.5]` example), and on the
   input side wherever the nodes happen to hold text. The asymmetry is deliberate: readability at the
   boundaries, efficiency in the interior.
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
- **API-local filesystem + Docker volume** — rejected on four specifics: it **cannot reach the inputs at
  all** (they sit on other nodes behind S3-API URIs, so a blob client is mandatory regardless and the
  filesystem becomes a redundant second backend), **single-writer coupling** (~200 GB of intermediates through
  a node that must stay stateless and horizontally scalable), **no AWS story** (Fargate has no shared host
  directory, so we'd build and test that second backend for real), and **no atomic multi-node visibility**
  (local-FS `rename` atomicity is single-kernel, so the "never read a torn partial" invariant would hold by
  deployment accident). It answers the demo and declines the design question.
- **NFS / EFS** — genuinely multi-node, but it too says nothing about inputs we do not own; close-to-open
  consistency downgrades `rename()`-based atomicity to a mount-option property; metadata cost dominates with
  ≈25k partials per job across concurrent jobs; EFS is ~10× S3's per-GB price for POSIX semantics we never
  use; and a wedged mount produces a worker that looks alive to the D7 lease while making no progress.
  Filesystem prices and filesystem risks for object-store behaviour.
- **DB (`bytea`) or in-message data** — the in-message variant is arithmetically dead (**8 MB vs SQS's 256
  KB cap** = 32× overshoot per message, ≈200 GB through a broker in aggregate; claim-check is the documented
  answer). The `bytea` variant passes the size check but not the volume one: ~200 GB of TOAST-ed values with
  WAL amplification would evict the buffer cache DM-004's claim query depends on and couple queue and data
  plane into one saturation point. Its one real merit — bytes and row in one transaction — is neutralised by
  deterministic keys: PUT-then-commit is already safe, so we never needed the atomicity we'd be paying for.
- **CSV partials** — 2.5× the bytes and a parse/format round-trip at every tree level, plus a
  decimal-precision footgun that would propagate through the reduce tree (DM-010). Its readability is only
  valuable at the boundaries — the result, and whichever inputs the nodes chose to hold as text.
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
- **Cross-node input reads dominate `map` time** — the deferred **data-locality** optimisation: bias the claim
  query so a worker prefers `map` tasks whose input node is co-located with it, instead of treating every one
  of the 800 GB of reads as equidistant. Deliberately not built now (it adds a placement dimension to a claim
  query DM-007 keeps deliberately simple); the trigger is measured cross-node read bandwidth, not intuition.
- **Cross-region workers** (same trigger as DM-004): cross-region GETs make transfer cost and latency
  dominate, pushing toward per-region buckets with replication and region-affine task placement.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Partial size | Exactly `C × 8` bytes; 8,000,000 B at C=1M (vs ~20 MB CSV) | `HeadObject` content-length assertion in an integration test |
| Cross-language round-trip | Bit-exact: bytes written by Python `np.tofile` read back by TS `DataView` and re-read by Python compare identical | Round-trip test in CI over random vectors incl. denormals, 0.0, negatives, and values spanning several orders of magnitude |
| Input reader accepts both encodings | The same F vectors read as `.csv` and as `.f64` produce identical partials | Fixture pair per encoding; assert `sha256` equality of the resulting partial objects |
| C validated at read | 100% of length mismatches (`len(buf) != C × 8`, CSV row count != C) are permanent errors with the URI in `last_error`; 0 truncated vectors summed | Fault-injection fixtures: short object, long object, non-multiple-of-8 `.f64`, wrong row count |
| Read allow-list enforced | 0 GETs to a bucket/host outside `INPUT_URI_ALLOWLIST`; a disallowed URI is rejected at `POST /jobs` with 400 | Submit off-list URIs (incl. link-local and internal hosts); assert 400 and, bypassing the API, assert the worker `BlobStore` also refuses |
| Idempotent overwrite | Re-running a completed `map`/`reduce` task produces a byte-identical object; final result unchanged | Force-replay 100 done tasks; `sha256` the object before/after; assert equal |
| No torn reads | 0 short/torn partial reads across 10k concurrent PUT/GET pairs | Reader asserts `len(buf) == C × 8` on every GET; count failures over a soak |
| Same code path | 0 storage-backend conditionals; MinIO→S3 switch is endpoint + credentials only | `grep` for backend branching in `BlobStore`; run the same suite against MinIO and S3 |
| Parse cost | Partial deserialisation < 1% of task wall time | Per-task timing split: GET, deserialise, compute, PUT |
| Intermediate volume | ≈200 GB written per max job (25k partials × 8 MB; 160 GB of it level-0 leaves), ≈200 GB read back | Sum of PUT content-lengths from the `events` table (D11) per job |
| API off the data plane | 0 bytes of input or partial data transit the API process | Result served by pre-signed URL; assert API egress ≈ metadata only |
