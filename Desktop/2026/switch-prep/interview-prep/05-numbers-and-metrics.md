# Extreme Numbers & System Metrics

Two halves: (A) the boundary numbers — what the system looks like at its edges and
where the ceilings are; (B) the metrics that measure whether it's *effective*
(correct), *efficient* (fast/cheap), and *reliable* (survives failure), each with its
formula, target, and where it's measured.

---

# A. The extreme numbers

## A.1 The input envelope

| Quantity | Value | Derivation |
|---|---|---|
| Bounds | 2 ≤ F ≤ 99,999 · 2 ≤ C ≤ 999,999 | brief: 1 < F < 100k, 1 < C < 1,000k (exclusive) |
| One file / one partial | **8 MB** binary (C=10⁶ × 8 B); ~20 MB as CSV (2.5×) | float64 |
| Max-job input | **≈ 800 GB** — read only, never written by us | 10⁵ × 8 MB |
| Smallest legal job | F=2, C=2: one map (count=2=F), zero merges, one finalize | same machinery, no special path |

## A.2 The task graph at maximum

| Quantity | Value | Formula |
|---|---|---|
| Map tasks | **20,000** | ⌈F/5⌉ |
| Merge (reduce) tasks | **≈ 5,000** over **7 levels** | ⌈(L−1)/(k−1)⌉; depth ⌈log₅⌈F/5⌉⌉ |
| Level series | 20,000 → 4,000 → 800 → 160 → 32 → 7 → 2 → 1 | ÷5 per level |
| Total tasks | **≈ 25,000** (+1 finalize) | |
| Demo job (F=1,000) | 200 map + 63 reduce + 1 finalize = **264 tasks** | 63 = 40+8+2+1... (50+10+2+1) |
| Depth growth | +1 level per 5× more files | logarithmic — F=10⁶ is only level 8 |

## A.3 Bytes in motion

| Flow | Bytes | Note |
|---|---|---|
| Input reads | 800 GB | across all workers' NICs in parallel |
| Intermediate writes | **≈ 200 GB** total; **160 GB is level 0 alone** | 25k partials × 8 MB; the k/(k−1)=1.25 amplification |
| Intermediate reads | ≈ 200 GB | each partial read once, one level up |
| Total data-plane traffic | ≈ 1.2 TB | vs control plane: ~25k rows × <1 KB ≈ 25 MB — a 50,000:1 ratio |
| Resident, per worker | **~16 MB** (accumulator + current buffer), any F | streaming fold |
| Resident, we own (storage) | ≈ 200 GB intermediates + result | inputs belong to the nodes |
| Fan-in economics | k=2 → 320 GB/15 levels; k=5 → 200 GB/7 levels; k=20 (loose reading) → 168 GB/4 levels | why we take the cap; what the strict reading costs (~15%) |

## A.4 Time

| Quantity | Value | Derivation |
|---|---|---|
| Task service time | **≈ 2.2 s** | map ≈ 108 MB moved (5×20 MB in + 8 MB out) at ~50 MB/s |
| Worker throughput | ≈ 0.45 tasks/s | 1/2.2 |
| Demo makespan | ≈ 2.4 min at W=4 | 264 × 2.2 / 4 ≈ 580 worker-s |
| Max-job work | ≈ **15.3 worker-hours** | 25k × 2.2 s |
| Max-job makespan | ≈ 3.1 h at W=5 · **≈ 29 min at W=32** | work/W + tree floor |
| The floor no W removes | ~8 serialized task latencies ≈ **18 s** | tree depth + finalize — the critical path |
| Serial-tail comparison | single accumulator: **~21 min** serial at 1 Gbps | 160 GB through one NIC — the DM-001 rejection number |

## A.5 Liveness & failure constants

| Constant | Value | Consequence |
|---|---|---|
| Lease / heartbeat / reaper | **30 s / 10 s / 5 s** | crash detected ≤ **35 s**; heartbeat has 3 chances per lease |
| Absolute task deadline | **300 s** | caps even a wedged-but-heartbeating holder |
| Attempts | 3 (finalize: **10**) | then task dead → job failed loudly — unless a count=F partial exists |
| Worst honest recovery math | crash at t=29.9 of a lease → ~35 s + 2.2 s redo ≈ 37 s per crash event | one task's blast radius |

## A.6 The ceilings — what breaks first, in order

| # | Ceiling | Number | First lever |
|---|---|---|---|
| 1 | Claim-poll latency | 500 ms idle poll | LISTEN/NOTIFY (drop-in) |
| 2 | DB connections | 2/worker + API pool 10 → W≈45 on default max_connections=100 | raise it; then PgBouncer (careful: transaction pooling × advisory locks) |
| 3 | Per-job pairing lock | ms-held ⇒ ~hundreds of commits/s per job; we do ~W/2.2 ≈ 15/s | optimistic/sharded pairing |
| 4 | Claim rate on SKIP LOCKED | comfortable ~1–10k/s; we need **≪1k/s** | SQS + outbox (the written trigger: >5k/s sustained) |
| 5 | S3 per-prefix request rate | ~3.5k PUT/s, 5.5k GET/s per prefix | shard the partials prefix |
| 6 | Events table | 2M-row / 7-day trim; ~50k rows per max job | already handled |
| 7 | W_max | 32 (validated at the API) | raise with #2/#3 |
| 8 | SQS message cap (why queue carries URIs) | 256 KB vs 8 MB partial — **32× over** | structural, not a tunable |

---

# B. The metrics — measuring the three properties

## B.1 Effectiveness (is it *correct*?)

| Metric | Formula / check | Target | Measured from |
|---|---|---|---|
| Result accuracy | max relative error vs single-node numpy oracle | ≤ 1e-9 (observed ~1e-15) | test suite golden/property tests |
| **Conservation audit** | Σ count over map-produced partials = F, per completed job | exactly F, always | `partials` table — the suite asserts it after chaos |
| Double-consumption | partials with consumed_by set = consumed exactly once | 0 violations (schema-guaranteed) | UNIQUE + guard |
| Completion truthfulness | jobs completed with a non-count=F root | **0** | join jobs × partials |
| Stranded-job detector | `job.stranded` events | **0** — any firing is a bug alarm, not noise | events |
| Backstop firings | reaper sweep finding quiet-but-unfinished jobs | **0** in normal operation | events |

The philosophy metric: every one of these is read from **state**, not accumulated
from events — the same principle as the completion proof itself.

## B.2 Efficiency (is it *fast and cheap*?)

| Metric | Formula | Target | Why it's the right lens |
|---|---|---|---|
| **Worker utilization** | busy-time / alive-time, while eligible work exists | > 90–95% | THE brief's stated criterion ("as little time as possible idling") |
| **Makespan ratio** | actual makespan / T*, where T* = total work ÷ aggregate fleet speed | ≤ 1.2 with a 3× straggler injected | measures the whole scheduling story in one number |
| Tail shape | last task finish − second-to-last | ≤ 2× mean task time | catches straggler damage directly |
| Fan-in histogram | % of merges at fan-in 5 | ≥ 95% steady-state; undersized ones ≤ tree depth | proves drain mode is a tail patch, not a leak |
| Overhead ratio | per-task fixed cost / (c·p) — claim+commit+partial-write vs useful work | < 5% | the chunk-size derivation's core quantity |
| Claim latency | p99 of claim round-trip | < 50 ms | queue health |
| Intermediate amplification | intermediate bytes written / input bytes | ≈ 0.25 (the k/(k−1) tax) | the tree's known price, watched |
| Stall gauges | **oldest_pending_age_sec, oldest_claimed_age_sec** | flat; growth = stall | the two most alert-worthy numbers on the dashboard |
| Cost per max job (AWS) | Fargate active-seconds + S3 requests + storage-days | ≈ $1–2 compute + ~$4 requests | ~15.3 worker-hours dominates |

## B.3 Reliability (does it *survive*?)

| Metric | Formula | Target | Measured from |
|---|---|---|---|
| Crash-detection latency | lease_expired event time − last heartbeat | ≤ 35 s | events |
| Recovery correctness | chaos test: kill a worker mid-job → job completes AND conservation holds | pass, always | the suite's chaos test |
| Retry rate | tasks with attempts > 1 / total | near 0 baseline; spikes = infra trouble | tasks |
| Dead-task rate | tasks reaching 'dead' | ~0; every one names its URI/error in last_error | tasks |
| Answer-preservation | jobs failed while holding a count=F partial | **0** (reaper refuses; emits needs_finalize) | events |
| Degradation modes | reaper down → recovery late, never wrong · supervisor down → W drifts · DB down → pause, no corruption · store down → bounded timeouts → normal retry path | each is "degraded, not incorrect" | design property, verified per component |
| Zombie safety | late commits by fenced-out workers | 0 rows matched — silently discarded | fence semantics |
| SSE integrity | event ids strictly increasing on the stream; resume via Last-Event-ID | no skips (the 1 s visibility lag is the guarantee) | suite asserts |
| API statelessness | kill the API mid-job | zero effect on the job (workers don't need it) | design property |

## B.4 The four numbers to say in an interview when asked "how would you measure this system?"

1. **Utilization while work exists** (>90%) — the brief's own criterion, directly.
2. **Makespan / T\*** (≤1.2 with an injected straggler) — the entire distribution
   story compressed to one ratio.
3. **Conservation audit = F, always** — correctness measured from state.
4. **Oldest-pending-task age, flat** — the single best early-warning signal a queue
   system has; nearly everything that can go wrong shows up here first.
