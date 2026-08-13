# Decision Q&A — 30 Questions with Full Answers, Plain Language

For each decision: the ten questions with answers you can say aloud, then how a
skeptic stress-tests the decision, and the weak points to own before they're found.

---

# Decision 1 — Aggregation Topology (how partial results become one answer)

### Q1. Why do workers exchange sums-with-counts instead of averages?

Because averaging averages gives the wrong answer whenever groups are different
sizes — and here they always are. Concrete: 12 files split 5+5+2; ten files hold 0.0
and two hold 1.0. True mean = 2/12 = 0.1667. Average of the three group-averages =
(0 + 0 + 1)/3 = 0.3333 — double the truth, with no error raised anywhere. Carrying
(sum, count) makes the weighting automatic: merge any groups in any order, divide by
F exactly once at the end. It's not a preference — one version is correct and the
other is silently wrong.

### Q2. Walk me through what happens to 20,000 partial results.

A partial is C numbers — the same size and shape as an input file (8 MB at C=1M).
So the "5 files at a time" limit applies to merging partials just like reading files.
Merging 20,000 things five-at-a-time takes rounds: 20,000 → 4,000 → 800 → 160 → 32 →
7 → 2 → 1. Seven levels, about 5,000 merge tasks — and each merge task is just
another task on the same queue, done by whichever worker is free.

### Q3. Why not one node that accumulates everything? It only needs 8 MB of RAM.

Correct about the memory — and that's why the lazy rejection ("it won't fit") is
wrong. The real problem is bandwidth: all 20,000 partials — 160 GB — must flow through
that one node's network card. At 1 Gbps that's ~21 minutes of pure transfer, and
adding more workers cannot shave a second of it, because it's serial by construction.
The tree moves the same bytes through *every* worker's network card in parallel.
Second problem: that node now holds irreplaceable state in RAM, which breaks restarts
and multi-instance deployment (see the stress-test section).

### Q4. Where does the brief say the limit applies to partials?

It doesn't — that's my documented assumption, and here's the reasoning. The brief
says the limit exists "to simulate RAM constraints." A partial is byte-for-byte the
same object as a file, so if RAM is the concern, it must count. The looser reading —
only literal input files count — self-destructs: with streaming (fold inputs one at a
time through an accumulator, ~16 MB resident no matter how many inputs) *nothing*
ever needs 5 things in memory, so the rule would forbid nothing and the job would
never need splitting — contradicting the brief's own "therefore you must split."
I also chose the strict reading because it's safe: a design correct under it is
correct under both readings, and the extra cost is only ~3 more tree levels.

### Q5. Why not shard by columns (indices) instead of by files?

Because the constraint counts files: a column-shard task still can't open more than
5 files, so sharding columns removes zero merging work. Worse, a "column" isn't a
real thing on disk — it's one number scattered across all F files — so every shard
must re-read every file: S shards means S × 800 GB of reads. It's the right tool for
a different problem: if C ever grew so large that one vector didn't fit in a worker
(~C > 100 million), you'd stream column blocks *within* tasks. That's written down as
the escape hatch.

### Q6. Why not build the whole task graph up front and know your exact progress?

Because wiring each merge to five *named* children means a merge waits for those
specific five — one slow child stalls its branch even when fifty other partials sit
ready. That re-creates the waiting problem at every one of ~5,000 internal nodes.
Since sums merge in any order, insisting on a particular order buys nothing — except
one real thing: identical merge order gives bit-identical output between runs. That
benefit is preserved as an opt-in flag rather than paid for by default.

### Q7. Two runs give bit-different outputs — is that a bug?

No — floating-point addition rounds differently depending on grouping order, and the
emergent tree's shape varies run to run, so the last decimal digits can wiggle
(~1 part in 10¹⁵). The error is still bounded far below anything meaningful, and if
bit-identical output ever became a requirement, the fix is known: merge in a fixed
canonical order (the opt-in from Q6).

### Q8. What does the tree cost you?

About 200 GB of intermediate writes at the biggest job (160 GB of that is the first
merge level) plus reading it back — pure overhead against 800 GB of input. Also:
progress can't be an exact "X of N tasks" because merge tasks are created on the fly,
and the output isn't bit-reproducible by default. All three are priced and accepted;
the first has a known lever (next question).

### Q9. Intermediate traffic is your biggest inefficiency — fix it.

Let a worker merge the partials of *its own* finished tasks locally before writing —
one write instead of several. That can cut the big first level from 160 GB toward
~32 GB. The trap to name: the local accumulation must stay aligned to task boundaries.
If a worker accumulates *across* tasks and flushes every N tasks, a crash makes it
ambiguous which tasks' work survived — you've traded bandwidth for correctness
bookkeeping. Keep the task as the unit of durability.

### Q10. Now compute the median instead of the mean.

The design question is: does the statistic merge? Sums merge (that's the whole
foundation); medians don't — you can't combine two medians into the right overall
median. Two ways out: exact — do it in rounds (workers count values in ranges,
binary-search the range holding the middle value; each round reuses all the same
machinery); approximate — use mergeable summaries (t-digest / KLL sketches), which DO
merge, so only the partial's payload changes and the queue, completion proof, and
failure handling all survive untouched. Variance, min, max: all merge — trivial swaps.

## How a skeptic stress-tests Decision 1

- **Hand you the memory argument** (Q3) hoping you'll parrot "won't fit in RAM" — the
  test is whether you know it's a bandwidth rejection.
- **Attack the assumption** (Q4) — "you invented the partial rule." The test is
  whether you present it as a derived, documented judgment with the vacuous-rule
  argument, not as fact.
- **Change the statistic** (Q10) — median/percentile. The test is whether you reach
  for "does it merge?" rather than panic.
- **Push the scale knobs one at a time**: C → 10⁸ (column streaming inside tasks),
  F → 10⁶ (one more level), values with huge magnitude spread (float64 headroom,
  Kahan as the named fallback).
- **Ask for the reversal triggers.** Every ITD ends with "what would make me undo
  this" — intermediate I/O > 40% of wall-clock → local combining; reproducibility
  required → pinned tree; F cap ≤ 25 → the machinery stops paying for itself.

**Weak points to own:** the ~200 GB write overhead is real; the strict constraint
reading costs ~3 extra levels vs the loose reading (~15% more merge I/O); the
file-shaped-partial argument is an interpretation, not a quote.

---

# Decision 2 — Work Distribution & Stragglers (how work meets workers)

### Q1. How does work get to workers?

Workers pull: a free worker asks the queue for the best next task; nothing is ever
assigned to a named worker. That single choice does the load balancing — a worker
holds work only while executing it, so a 3× faster worker simply comes back for more
3× as often. Completed-task counts end up proportional to actual speed with no
measurement, no tuning, no rebalancing step.

### Q2. Why not a scheduler that estimates each worker's speed and assigns proportionally?

Because assignment-in-advance is a bet on future speed, and the bet's loss is paid in
idle time. At the start you know nothing (even split), and any real fleet's speed
isn't stable anyway — a slow storage read, a cold cache, a noisy neighbor VM can
halve a worker's speed for a minute with no warning history gives you. Concretely:
even split of 12 files across a 1×/2×/4× fleet finishes in 16 s where ~8 s was
possible — one wrong guess nearly doubled the job. Pull never guesses: every claim
happens at the moment the worker is provably free. Push's one genuine prize —
sending a merge to the worker that already holds one of its inputs, saving a fetch —
is recoverable later as a claim-ordering hint.

### Q3. Quantify the straggler damage in both designs.

Push: a slow worker owns its assigned slice, roughly 1/W of the job — damage grows
with job size. Pull: a slow-but-alive worker damages exactly the one task in its
hands (~2 seconds of work), no matter how big the job. There's a classic result
behind this: greedy pull finishes within (ideal time + one task's time) — the penalty
is a constant, not a fraction of the job.

### Q4. Why five files per map task, not one for perfect balance?

Because each task has a fixed cost that doesn't shrink with the chunk: it must write
a full C-length partial (8 MB) and pay a claim + commit, however few files it read.
One-file tasks mean 5× the tasks, 5× the fixed costs, and 5× the partials the tree
must merge — for balance that pull already provides. The formal version: the optimal
chunk balances fixed cost against straggler risk (a square-root formula); at this
system's numbers it comes out around 32, so the RAM cap of 5 binds first. Take the cap.

### Q5. Why merge five at a time and not pair them off as they arrive?

Total merge traffic scales with k/(k−1) where k is the fan-in: pairs (k=2) → 2× the
leaf bytes = 320 GB and 15 levels; fives (k=5) → 1.25× = 200 GB and 7 levels. Bigger
fan-in is strictly cheaper and shallower, so take the biggest legal one.

### Q6. End of job: 3 partials left, nothing running, your rule says "wait for 5."

Without a patch: deadlock, forever — the 4th and 5th partial will never exist. The
patch (drain mode): when the job has nothing running and nothing pending, merge
whatever's there, 2–4 at a time. Cost: it can only trigger when the job is otherwise
silent, so at most ~one undersized merge per remaining level — about 7 extra tasks in
5,000, under 0.15% — to remove an infinite stall. And undersized merges are *correct*
for free, because partials carry counts (Decision 1's choice pays off here).

### Q7. Two workers commit this job's last two partials at the same instant. Walk through it.

The bug we found and fixed — tell it as a story. Each worker's commit transaction
checks "is anything else still running?" and counts waiting partials. Worker A's
snapshot still shows B's task as running (B hasn't committed yet) — and the row-skip
mechanism used for reading partials hides B's partial too. So A concludes "not my
job to merge" and commits nothing. B, symmetric, concludes the same. Both commit
having done nothing — and since merging is only ever triggered by a commit, no
trigger ever comes again. Job stranded forever at 99%, reachable with just 2 workers
and 7 files. Fix: a per-job lock around the pairing step, so the two commits take
turns — the second one *waits milliseconds*, then sees the complete picture (A's
partial committed, A's task done) and acts. There's a test that pins this exact
interleaving.

### Q8. Isn't that per-job lock a bottleneck?

It's held for single-digit milliseconds during a commit, and it's per-job — different
jobs never touch each other's lock. A worker commits roughly once per couple of
seconds, so a job would need hundreds of commits per second before the lock matters —
two orders of magnitude away. And the honest trigger is written down: if tasks ever
became sub-second at huge worker counts, pairing would need to go optimistic or
sharded.

### Q9. A worker is alive and heartbeating but running at 10% speed. What saves you?

Not the crash machinery — a heartbeating worker never trips a lease. Three things
bound the damage: pull means it only holds one task; the absolute per-task deadline
(300 s) caps even that; and the named cure is speculative duplicates — run a copy of
the projected-last task on a fast idle worker, first result wins (duplicates are
already harmless because outputs are idempotent). Deferred deliberately: duplicating
a task re-reads ~40 MB to save seconds, and our tasks are too simple to estimate
progress on. The trigger to adopt it is written down.

### Q10. Idle workers poll every half-second. Defend that.

At 32 idle workers with jitter that's ~64 tiny indexed queries per second — noise.
A claim that finds nothing retries once immediately (the head of the queue might have
been momentarily locked by another claimer) before sleeping. The zero-poll upgrade
(the database pushing "work arrived" notifications) is a named drop-in if measured
claim latency ever matters. Honest add: this is one of the places I'd spend a
benchmarking day.

## How a skeptic stress-tests Decision 2

- **The simultaneous-commit race (Q7)** — the deepest probe available. The test is
  whether you can trace both transactions from memory and explain why the row-skip
  reads made it *worse* (each worker undercounted and concluded "someone else will").
- **Attack your own fix (Q8)** — "your lock serializes everything." Test: do you know
  it's per-job, millisecond-held, and two orders from mattering — with a written
  trigger for when that changes.
- **The slow-but-alive worker (Q9)** — testing whether you know leases only catch
  *dead* workers, and what the actual backstops are.
- **Granularity from both sides**: "why not chunk of 1" (fixed costs ×5) and "why not
  chunk of 50" (a slow worker holding a 50-file chunk sets the job's finish time —
  the straggler ceiling; also the RAM cap forbids it).
- **"What if F < workers×5?"** — small jobs: the cap stops binding, and the honest
  answer is the straggler ceiling (never give a chunk the slow worker can't finish
  within the job's ideal time) with tapered sizing as the documented evolution.

**Weak points to own:** the poll loop leaves ~500 ms of claim latency on the table;
locality (push's prize) is unexploited; speculation is deferred so the last task of a
job runs at the slowest holder's speed, bounded only by the deadline.

---

# Decision 3 — Job Completion Detection (how the system knows it's done)

### Q1. How does the system know a job is finished?

Every partial carries a count of how many original files are inside it. Maps create
counts, merges add them, nothing can duplicate or lose them — so the counts on
unmerged partials always add up to exactly F. The moment a single unmerged partial
exists with count = F, that partial must contain every file exactly once: it IS the
answer. The check is one integer comparison inside the transaction that commits the
final merge — no counter, no watcher, no delay.

### Q2. Why not count down remaining tasks — the standard pattern?

Two independent failures, both silent. First, there's no number to start from: merge
tasks are created on the fly, so "N tasks total" doesn't exist until the job is over.
Second, the queue redelivers: a task can legitimately complete twice, and a second
decrement makes the counter hit zero early — job declared done with work missing,
wrong answer, no error. Every patch ("only decrement once per task") ends up
consulting the task's own status — at which point the counter is just a cached copy
of the truth, and the cache is the thing wired to the trigger.

### Q3. Show me the counter firing early even with atomic decrements.

Scoreboard says 1. The last map task commits: tick 1 → 0 — zero observed, finish
declared. One millisecond later that same commit spawns the merge task: 0 → 1. The
counter passed through zero legitimately, in the gap between "last map done" and "its
merge created." At that same instant, the conservation check reads the actual state:
the partial says count = 10 of 12 — not done. Facts read off state can't be fooled by
event timing.

### Q4. Prove the count check can't fire early or late.

At submit, the F files are dealt out across map tasks — each file to exactly one.
Maps turn k files into a count-k partial: k out, k in. Merges consume counts and emit
their sum: total preserved. Consumption happens exactly once per partial (guarded).
So the unmerged partials always partition the F files — their counts must sum to F.
One remaining partial ⇒ its count is F (can't be missed); count = F ⇒ all F files
folded in exactly once (can't be early). It's conservation of mass for data.

### Q5. Your proof assumes exactly-once consumption. What enforces it?

Two guards: a partial's "consumed-by" is set in the same transaction that creates the
merge task consuming it — under the per-job lock, so no race — and each task can mint
at most one partial (a uniqueness rule on the producing task). Honest framing: the
proof is only as strong as those premises, which is exactly why the locking and
fencing machinery isn't optional plumbing — it's what the proof stands on.

### Q6. Two workers both observe "done." Do you finish twice?

No. Acting on the discovery is a compare-and-swap: "flip the job from running to
finishing — if your flip succeeded, you arm the final step; if zero rows changed,
someone beat you, do nothing." A mirror swap guards finishing → completed. Two
one-line guards bracket the endgame; no interleaving produces two results.

### Q7. The final divide-and-write task keeps failing. What happens?

Original design flipped the job to failed after 3 attempts — discarding a fully
computed answer that was one 8 MB read away. Fixed with an asymmetry: the final task
gets 10 attempts (it's a trivial idempotent step), and the recovery process refuses
to fail any job that still holds a count = F partial — it raises an alert instead.
Principle: a computation that has proven itself complete must be unkillable by retry
bookkeeping.

### Q8. Any gap between "the proof is true" and "the finish actually runs"?

There was — the best catch in the whole review. The claim query originally served
only jobs in "running," but arming the finish flips the job to "finishing" first — so
the final task was invisible to every worker. Every job would have hung at 99%, on
the happy path, forever. One-line fix (serve both states), but the lesson is
permanent: a correct proof still needs its plumbing audited end-to-end.

### Q9. A polling watcher is simpler and robust. Why not that?

Conceded: it's robust, and it's a natural home for timeouts. But it adds up to a full
poll interval of delay at the most visible moment (the bar sitting at 99%), it's a
new process that itself needs health checks and single-instance guarantees (two
watchers must not both fire), and it re-discovers by patrol a fact the committing
transaction already knew at the instant it became true. Kept in demoted form: a slow
background sweep that should never find anything — a smoke alarm, not the mechanism.

### Q10. Files keep arriving — a stream, not a batch. Does completion survive?

No, and knowing why is the point: count = F is a proof only because F is sealed at
submit. Unseal F and the predicate means nothing. The fix is an explicit "inputs
sealed" marker per job (or windowed sub-jobs), and this exact boundary is written in
the decision record as its reversal trigger. Naming your design's breaking condition
before the interviewer does is the strongest move available.

## How a skeptic stress-tests Decision 3

- **Demand the early-fire trace (Q3)** — slogans don't survive; the
  passes-through-zero interleaving does.
- **Attack the premises (Q5)** — "your proof is circular; it assumes the guards
  work." Test: whether you can point at the two specific mechanisms and admit the
  dependency plainly.
- **Hunt the plumbing seams (Q8)** — the proof-to-action gap. Telling the
  found-and-fixed story turns the attack into your best material.
- **Break the sealed-input assumption (Q10)** — streaming, appending, growing F.
- **Endgame races (Q6, Q7)** — double-finish and the failing finisher.

**Weak points to own:** the invariant is only as good as the consumed-once guard (a
bug there strands jobs — by design it strands rather than lies, and a detector event
fires); the two-part condition includes a task-state read, so "purely data-derived"
is 90% true, not 100%; streaming inputs genuinely break it.
