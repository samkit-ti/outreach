# Gap Analysis — Alternative Treatment vs This Design

Comparison of an independent, high-quality treatment of the same problem (chunk-size
optimization + reduce trace + counter-based completion) against this design. Three
buckets: what it has that we lack, what we have that it lacks, and where we agree.
Prep material — knowing both sides of every divergence is the win.

---

## 1. What it has that we don't (and verdicts)

### 1.1 Formal chunk-size derivation — ADOPT AS DEFERRED NOTE
It frames granularity as Q||C_max (makespan on uniformly-related machines) and derives
a square-root rule — `c* = √(F·o/(α·W·p))`, EOQ-shaped: fixed per-task overhead
amortized against linear work — then shows the binding constraint under heterogeneity
is the **straggler ceiling** `c·p_slowest ≤ T_target`, with a sharply asymmetric risk
curve (undershooting c costs a few %, overshooting 50–150% → round down).
Its own conclusion: **at F ≥ ~5W every bound is slack and the RAM cap binds — c = 5
always** — which is exactly our fixed choice. The derivation only matters for the
small-F regime (F < 5W).
- Also brings the parallel-loop-scheduling literature: GSS (guided), Factoring, TSS
  (tapered chunks), speed-proportional dispatch with EWMA `p_i` estimates and a probe
  phase, straggler cutoff (stop feeding the slowest near the tail).
- **Our position:** DM-002 argues c = 5 from overhead ratio and defers everything
  adaptive. The formal backup and the small-F caveat are worth one deferred bullet:
  *"Adaptive chunk sizing for small-F jobs (F < 5W): straggler ceiling
  c ≤ T*/p_slowest, tapered dispatch (Factoring); trigger — small-job tail latency
  dominated by a single slow worker's chunk."* Key nuance it concedes: tapering with
  unknown speeds is a gamble on the first dispatch (slow worker grabs the big chunk),
  which is why our pull-at-fixed-c is the safer default.
- One sharp observation to keep: **per-task overhead is O(C), not O(1)** — every task
  emits a full C-length partial (8 MB) no matter how few files it consumed. That is
  the real cost of fine-grained chunking here.

### 1.2 In-worker combining as a first-class mechanism — ALREADY DEFERRED; NOTE THE TRAP
It makes the combiner central: a worker keeps one accumulator **across chunks** and
flushes every FLUSH_EVERY=50 chunks → 20,000 partials become 400 (50× less reduce
traffic), with FLUSH_EVERY as a durability-vs-throughput dial.
- **The trap it glosses over:** cross-task accumulation breaks task-level idempotency.
  Its partials are per-*flush*, not per-*task* — a crash loses up to 50 chunks of
  acknowledged... actually un-acked work, and the retry/ack story gets genuinely murky
  (which tasks does a lost flush "un-complete"?). Our per-task partial keeps every
  retry trivially idempotent (deterministic key = task id). Our version of this
  optimization (DM-001 failure condition 1) combines only *within* a worker's already-
  claimed work before writing — same 50× lever available, sanity preserved by keeping
  the task the unit of durability. If asked: "combiner yes, but flush boundaries must
  stay aligned to task boundaries or you trade correctness bookkeeping for bandwidth."

### 1.3 Single-task short-circuit — NOTE, DELIBERATELY NOT TAKEN
For total_tasks == 1 it fuses the divide into the map task and skips the reduce/
finalize round-trip. Saves one queue round-trip on tiny jobs. We deliberately kept
one uniform path (map → finalize even at F ≤ 5): one state machine, no special cases,
and the finalize CAS is what guards double-completion. Defensible both ways; ours
optimizes for invariant simplicity, theirs for tiny-job latency.

### 1.4 Self-describing partial files — COSMETIC
Its partial format embeds a header (magic, C, n, chunk_idx). Ours keeps `count` in the
DB row (authoritative) — the DB is the control plane. Embedding n in object metadata
is a debug nicety we already noted; a binary header adds parsing on both sides for
information the transaction already owns.

### 1.5 Vocabulary worth having
Q||C_max, EOQ analogy, OpenMP `schedule(dynamic,c)` / `schedule(guided)`, GSS/
Factoring/TSS, deficit round-robin (DRR). Name-drops that signal depth when the
granularity question comes up.

## 2. What we have that it lacks (the defend list)

### 2.1 Its "one genuine hole" is our headline argument
Its counter design has a self-admitted fatal window: **crash after committing the
decrement but before enqueueing the reduce → the job hangs forever**, patched with a
transactional outbox or a sweeper. That hole exists *only because its queue is
external to its database*. Our queue IS the database: partial-commit + pairing +
reduce/finalize enqueue are **one transaction** (DM-004). The dual-write it bolts an
outbox onto is the exact scenario that decided our queue technology. Its §failure-(b)
is DM-004's argument written by someone who hit it.

### 2.2 Completion: counter vs proof
It uses a guarded atomic decrement (`UPDATE tasks … WHERE status='RUNNING'` gate, then
`remaining_tasks - 1 RETURNING`) — well executed, and its guard against double-
decrement is correct. But it works only because its task graph is **static** (all map
tasks known at submit, one reduce armed at zero). Our task graph is dynamic (reduce
tasks created by eager pairing), which is precisely DM-003's argument that a counter
cannot even be initialized here. Its `n_total == F` assert inside the reducer is our
conservation invariant demoted to a runtime checksum — we promote it to the completion
*mechanism*.

### 2.3 Its reduce phase is a barrier; ours overlaps
Its reduce arms only when the counter hits zero — a full map/reduce barrier, which is
how it ends up computing a 160 s serial tail and then needing the combiner + a fan-in-
20 tree to fix it. Our eager pairing never has the barrier: reduces run *while* maps
run, and the tail is drain-mode fan-in. Also note: its tree uses fan-in 20 —
implicitly reading "≤5 files at a time" as applying to input files only. We surfaced
that letter-vs-spirit choice explicitly and took the strict reading (a partial is
file-shaped ⇒ K binds reduces ⇒ recursion). Know both readings; ours is the
conservative one and we can argue either.

### 2.4 Fairness: ORDER BY vs a dispatcher component
It diagnoses the same FIFO head-of-line blocking and prescribes per-job queues + a
round-robin/DRR dispatcher — a new component and dynamic queue management (our DM-007
rejected alternative). Our least-in-flight ORDER BY gets the same round-robin effect
inside the claim query with zero new parts.

### 2.5 Fencing and the wedged worker
Its lease story has heartbeat + reaper (same 5 s/15 s instincts as ours) but no
fencing-token rotation and no absolute deadline — its "lease was stolen" case is
handled by a status guard on the task row only. Ours: per-claim token, token+status-
fenced commits AND heartbeats, reaper rotates the token, TASK_DEADLINE caps the
wedged-but-heartbeating worker.

### 2.6 Whole subsystems absent from its treatment
Admission control (413/429), API idempotency, SSRF allow-list for caller-supplied
URIs, result delivery (pre-signed vs proxy), W-via-API reconciliation, SSE
observability with the monotone coverage-based progress bar, stranded/needs-finalize
detectors, finalize retry-budget asymmetry. (Fair: its scope was scheduling + reduce.)

## 3. Where both designs independently agree (high-confidence ground)

(Σ, n) monoid partials and the mean-of-means counterexample · division by F exactly
once · raw float64 binary partials (8 MB vs ~20 MB CSV) · deterministic output paths →
idempotent retries · atomic write (tmp+rename / single PUT) · guarded terminal-state
CAS · float64 accumulators with the O(n·ε) vs O(log n·ε) pairwise argument, Neumaier
rejected as overkill · byte-reproducibility via sorted merge order as an opt-in ·
30 s visibility timeout too coarse → heartbeat + reaper at ~5 s cadence · speculative
execution safe because reduces are idempotent, deferred as an evolution · per-index
(column-direction) reduction with row-shaped access, O(C) memory · cleanup off the
critical path.

## 4. Actions taken / recommended

1. **Added (recommended)**: one deferred-optimization bullet for adaptive/tapered
   chunk sizing in the small-F regime with the straggler-ceiling rule (04 §4.2,
   DM-002 evolution).
2. **No change**: combiner stays task-aligned; short-circuit stays untaken; counter
   stays rejected — each now with a sharper articulated reason (above).
3. **Interview prep**: rehearse §2.1 — "the alternative design's own failure analysis
   contains the argument for our queue choice" is the strongest cross-validation in
   this file.
