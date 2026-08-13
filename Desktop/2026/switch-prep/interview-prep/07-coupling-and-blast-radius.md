# Coupling & Blast Radius — What Holds What Up, and What Breaks Where

Three layers: the **rigid spine** (couplings that are load-bearing — change one end
and the other end fails, sometimes silently), the **change-impact matrix** (flip a
decision, read off the damage), and the **designed seams** (places built to be
swapped cheaply). The one-line thesis: this design deliberately concentrates its
coupling into one place — the database transaction — so that everything else can
stay loose.

---

## 1. The rigid spine — load-bearing couplings

**S1. (sum, count) partials ⟷ everything downstream.**
The tightest coupling in the system. The counts are simultaneously: the correctness
of unequal merges (drain mode's 2–4 fan-in), the correctness of any F not divisible
by 5, AND the completion proof itself (count = F). Remove the count — carry means —
and three subsystems fail at once, all silently: drain merges compute wrong values,
tail chunks are mis-weighted, and completion has nothing to check. This is why the
payload decision is upstream of everything in the DAG.

**S2. Eager pairing ⟷ the advisory lock ⟷ the reaper-as-trigger.**
Pairing is the only thing that ever creates merges and the only thing that ever
detects completion — and it only runs on commits. That makes its trigger set
sacred: (a) the per-job lock (without it, two simultaneous committers each
undercount and both decline — job strands forever, reachable at F=7/W=2);
(b) pairing running after *every* fenced commit, even no-op duplicate ones;
(c) the reaper pairing for every job it touches. Remove ANY of the three and a
reachable interleaving strands jobs with no future trigger. These three are one
mechanism wearing three coats.

**S3. Consume-at-creation ⟷ redelivery safety.**
A merge's input partials are marked consumed in the transaction that *creates* the
merge task — not when it runs. That freeze is what makes a redelivered merge
harmless (both executions read the same frozen inputs, write the same key). Move
consumption to execution time and redelivery can double-consume → counts inflate
past F → the mean is silently wrong or the job hangs on a proof that can never fire.

**S4. Queue-inside-the-database ⟷ five mechanisms at once.**
The single most consequential coupling, and it's deliberate. Because the tasks table
IS the queue, all of these are *one-transaction cheap*: (1) consume-partials +
enqueue-merger atomically (the requirement that chose the technology); (2) fenced
commits and heartbeats as conditional UPDATEs; (3) leases and deadlines as columns
the reaper can sweep; (4) fairness as an ORDER BY; (5) submission birthing the job
and all its maps atomically. Swap the queue for SQS and all five need replacements:
an outbox + relay (new component), visibility-timeout semantics instead of token
rotation, a dispatcher for fairness, and a two-system consistency story. That's not
"change one line," it's "redesign the failure model" — which is why the switch
triggers are written down and narrow.

**S5. Deterministic output keys ⟷ at-least-once delivery.**
Retries are harmless *because* a retry writes identical bytes to an identical name.
Key by attempt number instead and every guarantee built on "the overwrite is a
no-op" dissolves: zombie PUTs become orphans, duplicate work becomes visible state.
Corollary coupling: the result key is job-derived, which is safe only because the
running→finalizing CAS guarantees exactly one finalize ever exists — weaken the CAS
and the "one writer" premise of that key dies with it.

**S6. Fencing tokens ⟷ reaper rotation ⟷ heartbeat conditions.**
Three clauses that only work as a set: the token is minted per claim, the reaper
NULLs it on requeue, and both commit and heartbeat require token+status to match.
Drop the rotation → a stale token still matches → a zombie's heartbeat can resurrect
a requeued task. Drop the deadline conjunct → a wedged-but-heartbeating worker holds
a task forever. Each clause looks redundant until you remove it.

**S7. The claim query's job-status filter ⟷ completion.**
Serving `('running','finalizing')` is one line, and it's the line the whole endgame
hangs on: completion flips the job to finalizing *before* the finalize task exists,
so a filter of 'running' alone makes that task invisible to every worker — every job
hangs at 99% on the happy path. (Found by review; the tightest small coupling in
the system.)

**S8. Worker's two DB connections ⟷ heartbeat-during-execute.**
The heartbeat thread must beat while the main thread works, and the commit is a
multi-statement transaction — one connection cannot serve both. Collapse to one
connection and either the heartbeat joins (and dies with) the commit transaction,
or the two threads corrupt the wire protocol. Also: the heartbeat must STOP before
the commit opens, or it contends with the fenced update on the same row.

**S9. Sealed F ⟷ the completion proof.**
count = F is a proof only because F is fixed at submission. Any change that unseals
F — streaming inputs, appendable jobs — kills completion detection outright, not
partially. (Written as the decision's reversal trigger; the fix is an explicit
input-sealed marker.)

## 2. The change-impact matrix

| If you change this… | Breaks immediately (loud) | Breaks silently | Survives untouched | Cost to do it safely |
|---|---|---|---|---|
| **Carry means instead of (Σ,n)** | completion (nothing to check) | drain merges, F%5 tails → wrong means | topology shape, queue, workers | none — this is just wrong |
| **Remove the advisory lock** | — | jobs strand at tail (mutual-decline), rare & unreproducible in dev | everything else | replace with equivalent serialization + re-prove |
| **Consume partials at execution, not creation** | — | double-consume under redelivery → counts > F | — | full redelivery re-analysis |
| **Swap Postgres queue → SQS** | fenced commits, atomic pairing, ORDER-BY fairness, lease semantics | dual-write windows until outbox lands | executors, blob layer, UI, math | outbox + relay + dispatcher + new failure model (~the written triggers' price) |
| **Loosen K to “input files only” (fan-in 20+ merges)** | — | nothing — it's legal under that reading | all correctness machinery | ~3 fewer tree levels, ~15% less merge I/O; docs/argument rewrite; the combining question mostly evaporates |
| **Flip claim priority (map before finalize/reduce)** | — | finalize/merges starve behind map floods; jobs pile at 99%; partial storage balloons | correctness (eventually completes) | it's a CHECK constraint — the DDL refuses; that's the point |
| **Serve only 'running' in the claim filter** | every job hangs at 99%, forever | — | everything until the endgame | don't. (S7) |
| **Remove drain mode** | jobs with tail partials < 5 deadlock | — | full-fan-in phase | only safe if leaves ≡ 1 mod 4 — i.e., never |
| **Remove the absolute deadline** | — | wedged-but-heartbeating worker holds a task indefinitely | crash handling (leases still work) | need some other cap on self-reported liveness |
| **Remove token rotation in the reaper** | — | zombie heartbeat can resurrect a requeued task | commit fencing (status guard still saves commits) | rotate somewhere else, or add epoch numbers |
| **Make the API hold per-job state** | multi-instance deploys, rolling restarts | split-brain double-folds if ownership races | workers (they never talk to the API) | sticky routing + fenced ownership + handoff — the whole DM-001 accumulator critique |
| **Progress = done/total tasks** | — | bar moves backwards (UI trust, not correctness) | everything | nothing — it's why coverage was chosen |
| **Drop the SSE 1-second lag** | — | resumed clients permanently skip events that committed late | live viewing | snapshot-horizon machinery (priced, deferred) |
| **Lower finalize attempts to 3 / drop the count=F guard in the reaper** | — | a proven answer can be discarded by retry bookkeeping | — | keep the asymmetry; it exists for this |
| **Unseal F (streaming inputs)** | completion detection, entirely | — | topology, scheduling, failure model | input-sealed marker or windowed jobs (the written trigger) |
| **Change the statistic to median** | payload + completion redesign | — | queue, scheduling, failure model, delivery — the *machinery* survives | sketches (t-digest) if approximate; rounds of the same machinery if exact |

Read the pattern in column two: **almost every dangerous change fails silently.**
That's not an accident of this table — it's why the design puts correctness into
things that can't drift (names, transactions, conserved counts) rather than into
behavior that reviewers would have to keep re-checking.

## 3. The designed seams — where change is cheap on purpose

- **Storage backend:** MinIO ↔ S3 is configuration; the blob layer is one interface
  with two guards. Node-owned inputs could become HTTPS endpoints behind the same
  allow-list.
- **The queue, eventually:** the QueueAdapter seam + written triggers (sustained
  >5k tasks/s, cross-region, multi-service) — expensive change, but *scoped* in
  advance rather than discovered in production.
- **W actuation:** the reconciler's compare-and-converge loop is actuator-agnostic —
  docker locally, ECS in the cloud, same brain.
- **Result delivery:** 302-presigned vs inline proxy is a query parameter.
- **Formats:** input parsing is extension-dispatched; adding Parquet is one branch.
- **Fairness policy:** least-in-flight generalizes to weighted fair queuing by
  editing one ORDER BY.
- **Deferred add-ons that bolt on without surgery:** speculation (idempotency already
  makes duplicates safe), LISTEN/NOTIFY wake-ups, in-worker combining (as long as it
  stays task-aligned), data locality as a claim-order hint, weighted FedAvg (payload
  gains one vector).

## 4. The interview take

> "The coupling is deliberately asymmetric. Everything correctness-critical is fused
> into one place — the database transaction — where consume, enqueue, fence, and
> the completion check commit or vanish together; that's the rigid spine, and the
> expensive-to-change decision (the queue) is expensive *because* it carries five
> mechanisms at once, which is exactly why it was chosen last, from a derived
> requirement. Everything else — storage, actuation, delivery, formats, policy — is
> behind seams that swap by configuration. And the danger profile is honest: the
> changes that break things loudly are cheap mistakes; the ones that break silently
> are precisely the mechanisms the design moved into unlosable places — names,
> conserved counts, single transactions — so they can't drift in the first place."
