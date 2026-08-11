# Interview Prep — Walkthrough Script + Numbers Card + Weak Spots

**NEVER push this folder to dynamo-R2.** It's outside `distributed-mean/`, so the
subtree export can't include it.

---

## A. The 5-minute walkthrough (rehearse aloud)

**Open with the shape, not the components.**

> "Strip the wrapper and this is a distributed fold. The output at index i is the sum
> over F files divided by F — and sums are associative and commutative, a monoid.
> That one algebraic fact drives every decision I made, because it means partial
> results can be combined in any order, in any grouping, by any worker — no
> coordinator, no barrier, no ownership."

**Then the constraint's hidden second edge.**

> "The 5-files-at-a-time RAM limit looks like a mapper constraint, but a partial
> result is C floats — exactly file-shaped. So the limit binds *combiners* too.
> Combining 20,000 partials five at a time forces a recursive 5-ary tree, about
> seven levels at the max job. Recursion isn't a choice I made; the constraint
> makes it."

**Then the two decisions I'd fight for.**

> "One: workers exchange (sum, count) pairs, never means — averaging averages is
> silently wrong for unequal group sizes, and unequal groups are the normal case
> here. Two: the tree is never planned. Whenever five unconsumed partials exist,
> whoever committed the last one atomically claims them and enqueues a reduce. So
> fast workers combine results while slow workers are still mapping — there is no
> barrier anywhere, and a straggler's blast radius is one task."

**Then completion — the part they flagged as most interesting.**

> "Completion is a proof, not a counter. Map and reduce both conserve the total
> count of covered files, and consumption is exactly-once. So a job's unconsumed
> partials always partition its F files — the moment a single partial exists with
> count equal to F, that partial *is* the answer. It can't fire early and can't be
> missed. A counter can't even be initialized here because reduce tasks are created
> dynamically."

**Then the queue, framed as a consequence.**

> "Those two mechanisms created a hard requirement: consume-partials and
> enqueue-their-reducer must be atomic. With an external broker that's a dual
> write — either order fails in a different way, one hangs the job silently, the
> other double-counts sums. The standard fix is a transactional outbox, which is a
> Postgres queue you then also pay SQS to sit in front of. So the tasks table IS
> the queue, claimed with FOR UPDATE SKIP LOCKED. Load honesty: ~25k tasks per max
> job at seconds each — claim rate is two orders of magnitude inside what that
> pattern handles. And I wrote down the exact triggers that would move me to SQS."

**Close with operations.**

> "Everything else is making retries harmless instead of impossible: deterministic
> output keys so a retry overwrites itself, fenced commits and heartbeats with
> token rotation, an absolute deadline for the wedged-but-heartbeating case.
> Fairness is one ORDER BY — least-served job first. W is a thermostat: the API
> writes a desired number, a supervisor converges reality to it. And it all runs:
> docker compose up, the spec's own example returns exactly 2.5, 3.5, 4.5, and a
> 23-test black-box suite passes against the live system, including killing a
> worker mid-job."

## B. Numbers card (memorize — say these unprompted)

| Quantity | Value |
|---|---|
| Bounds | 1 < F < 100k, 1 < C < 1,000k; K = 5 |
| One file / one partial | C×8 B ≈ **8 MB** at C=10⁶ (~20 MB as CSV, 2.5×) |
| Max-job input | ≈ **800 GB** read (never written by us — inputs pre-exist) |
| Map tasks | ⌈F/5⌉ = **20,000** |
| Reduce tasks | ≈ **5,000** over **7 levels** (20k→4k→800→160→32→7→2→1); depth = ⌈log₅⌈F/5⌉⌉ |
| Total tasks | ≈ **25k**; demo job F=1000: 200 map + 63 reduce + 1 finalize = **264** |
| Intermediates | ≈ **200 GB written** (160 GB is level 0 alone), ≈200 GB read back |
| Task service time | ≈ **2.2 s** (map: 5×20 MB in + 8 MB out ≈ 108 MB at ~50 MB/s) |
| Makespans | demo ≈ 2.4 min at W=4; max job ≈ 15.3 worker-hours → ~3 h at W=5, ~29 min at W=32 |
| Liveness | lease **30 s** / heartbeat **10 s** / reaper **5 s** → detection ≤ **35 s**; deadline **300 s** |
| Attempts | 3 (finalize: **10**) |
| W | default 4, W_max **32**; 2 DB connections per worker |
| Queue capacity honesty | SKIP LOCKED comfortable to ~1–10k claims/s; we need **≪1k/s** |
| SQS message cap | 256 KB — an 8 MB partial exceeds it **~32×** |
| Float64 | ε ≈ 1.1e-16; tree error ~9e-16 at F=10⁵ vs ~1.1e-11 naive serial; max Σ per index < 2⁵³ headroom |
| Fan-in economics | reduce reads scale k/(k−1): k=5 → 200 GB, k=2 → 320 GB |
| FIFO convoy | 3-task job behind 25k tasks ≈ hours for ~15 s of work; fairness costs the big job ~0.01% |

## C. Honest weak spots — own them before they're found

Say "good question — that's a known limit, here's the boundary" and give the fix.

1. **ITD Success-Metrics numbers are targets, not measurements** (except what the
   test suite verified live). If pressed: the suite measured correctness, chaos
   recovery, and fairness; throughput/latency percentiles are modeled, not benched.
2. **Claim query cost** — the inflight CTE is an aggregate over claimed rows per
   claim. Fine at W≤32; at hundreds of workers it needs a materialized in-flight
   counter (written down in DM-007's failure condition).
3. **Events table growth** — append-only with a retention trim; the SSE tail reads
   1 s behind to dodge commit-order gaps. The honest cost: dashboards lag reality by
   a second, and gapless-exactness needs snapshot-horizon machinery we didn't build.
4. **Per-job advisory lock serializes pairing** — milliseconds per commit, so ceiling
   ≈ hundreds of partial-commits/s *per job*. Fine here; a job with sub-second tasks
   at huge W would need sharded or optimistic pairing.
5. **Supervisor mounts docker.sock** — root-equivalent, demo-only, called out in
   HLD §9; on AWS it's an IAM-scoped ECS call.
6. **No auth** — `PATCH /system/workers` is an unauthenticated fleet control;
   deliberate scope, named in the docs.
7. **Drain-mode nondeterminism** — results reproducible to ~1e-15 but not
   bit-identical run-to-run; the deterministic-tree flag is the documented opt-in.
8. **Generation descoped** — the harness plays the nodes. If they wanted the system
   to generate: it's a fourth task type that seeds maps on completion; we removed it
   when the setting became "inputs pre-exist" and the docs say so up front.
9. **Dashboard needs a reachable API** — the Vercel page is static; live demo means
   localhost or a tunnel.
10. **What the build actually caught** — be ready to tell these stories proudly:
    the presigned-URL-signed-against-internal-hostname bug (caught by the suite),
    and the design-review catches: the claim query that couldn't serve `finalizing`
    (no job could ever complete), the pairing mutual-decline race (reachable at F=7,
    W=2), the unfenced heartbeat, the priority-direction inversion.

## D. Numbers-free one-liners to have loaded

- "Idempotent state predicates survive at-least-once delivery; mutable event
  counters don't."
- "The letter of the constraint is 5 files; its spirit is 'no node may see the whole
  job' — I honored both, and I can tell you exactly what changes under the looser
  reading (fan-in ~20 tree, two levels shallower)."
- "Every correctness mechanism lives in something that can't drift: a filename, a
  transaction, a conserved count, a desired-state row."
- "I can tell you the exact trigger that reverses each decision — they're written in
  the ITDs as failure conditions."
