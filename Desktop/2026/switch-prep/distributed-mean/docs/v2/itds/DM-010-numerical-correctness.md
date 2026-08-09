# ITD: DM-010 — Numerical Correctness of the Mean

**Date:** 2026-08-10
**Author:** Samkit Shah
**Status:** DECIDED
**Related:** DM-001 (aggregation topology), DM-002 (adaptive fan-in / stragglers), DM-004 (queue), DM-005 (storage & formats), DM-006 (idempotency), ../02-hld.md, ../CONTEXT-BRIEF.md

---

## Problem Statement

The result of a **job** is a vector of C means, each computed from F addends that were summed
by different **workers**, in a nondeterministic order, across ~7 levels of a reduction tree
(DM-001). At the envelope maximum this is **F = 100k addends per index, C = 1M indices** —
10¹¹ float64 additions per job. This ITD fixes the arithmetic: the accumulator type, what a
**partial** carries, where the division happens, and the resulting error bound. The target is
a **relative error ≤ 1e-15** per index against a single-node `numpy.mean(axis=0)` oracle, with
**no overflow and no silent precision loss anywhere in the stated envelope**, and no
per-element compensation machinery unless the bound demands it. The bar to clear is
**parity with the numpy oracle**, not superiority over it — numpy already sums pairwise, so
the honest goal is that distributing the work costs nothing in accuracy.

---

## Context

What actually determines the answer here:

- **Value bounds are ours to choose, and we chose them (D9): uniform [0, 1) float64.** So the
  largest possible sum at any index is **< F ≤ 100k**, against float64's exact-integer ceiling
  of **2⁵³ ≈ 9.007 × 10¹⁵**. We are ~11 orders of magnitude from the precision cliff. This one
  fact makes most of the exotic options unnecessary — and saying *why* they are unnecessary is
  more defensible than reaching for them.
- **float64 machine epsilon is ε = 2⁻⁵³ ≈ 1.11 × 10⁻¹⁶** (unit roundoff; ulp spacing at 1.0 is
  2.22 × 10⁻¹⁶).
- **Error growth depends on summation *shape*, not just on the type.** Serial (naive)
  accumulation of n addends has a worst-case relative error bound **O(n·ε)**; pairwise
  (binary/tree) summation has bound **O(log₂ n · ε)** — see
  <https://en.wikipedia.org/wiki/Pairwise_summation>. Our 5-ary tree is a pairwise-summation
  variant with base 5, giving **O(log₅ F · ε)**.
- **A realistic single-node baseline is *already* pairwise.** `numpy.mean` /
  `numpy.add.reduce` use pairwise summation internally (blocked, with an unrolled base
  case), so they carry the **O(log n · ε)** bound too — not O(n·ε). This matters for
  honesty: our oracle *is* numpy, so the tree does not beat the oracle and was never going
  to. The **O(n·ε)** figure belongs to a hand-written naive serial accumulator
  (`for f in files: acc += f`), which is the only baseline the tree is ~10⁴× tighter than.
- **The tree shape is already forced by DM-001**, for reasons that have nothing to do with
  numerics: a partial is file-shaped (C float64s = **8 MB**), so **K = 5** applies to reduces
  as well as to files, making reduction recursive — **20,000 leaf `map` tasks, ≈5,000 `reduce`
  tasks, ~7 levels** at F = 100k. The numerical benefit is a free consequence, and that is the
  interesting part of this ITD.
- **`count` is an integer**, so the completion test `count == F` (DM-001) is exact — there is
  no float comparison anywhere in job-completion logic. Counts are summed in Python `int` /
  `BIGINT`, never in float.
- **Order is nondeterministic** because D3 pairs partials eagerly as they commit (DM-002).
  Floating-point addition is commutative but **not associative**, so run-to-run results agree
  to within the error bound but are not guaranteed bit-identical.
- **Partials are stored as raw little-endian float64** (D6 → DM-005), so a partial round-trips
  through the object store with **zero** representation loss. Only the final result is CSV, and
  it is written with 17 significant digits (`repr`-round-trip precision) so the text form loses
  nothing either.

---

## Alternatives

### Naive serial float64 accumulation on a single node

The baseline any candidate would write first: one process, one C-length accumulator, loop over
all F files adding each into the accumulator, divide by F at the end. Note this is the
**hand-written naive** loop specifically — a single-node `numpy.mean(axis=0)` is *not* this
alternative, because numpy sums pairwise internally and lands on the tree's error bound, not
this one.

**Pros:**
- Simplest possible code and the obvious mental model; it is the correct *oracle* for small F
  and is exactly what the test suite compares against.
- Fully deterministic and bit-reproducible — fixed order, fixed result, every run.
- Zero intermediate storage and zero coordination.
- Even at the envelope its error, ~2.2 × 10⁻¹¹ relative worst case, is *good enough for this
  problem*. Honesty matters here: this alternative is not numerically broken.

**Cons:**
- Error bound is **O(F·ε) = 100k × 1.11e-16 ≈ 1.1 × 10⁻¹¹** relative worst case — about
  **10,000× looser** than the tree's bound, and equally 10,000× looser than a plain
  `numpy.mean` on one node, which is the real reason no one should write this loop. Fine for
  a mean of random uniforms; not fine as a general accumulation pattern, and the worst case
  is realised when addends are similar in magnitude, which is exactly our situation.
- It is **architecturally unavailable**: it needs one node to read all 800 GB of input, which
  violates the K = 5 constraint's purpose and is the central-accumulator design already
  rejected in DM-001 on ~160 GB of single-NIC bandwidth.
- Serial in wall-clock: no parallelism at all, so it cannot meet the exercise's premise.
- Drift is *systematic*, not random: as the accumulator grows toward 100k, each new addend
  (< 1) is added at a coarser ulp, so late addends are progressively under-weighted.

### float64 with (sum, count) partials over the 5-ary reduction tree *(chosen)*

Workers accumulate in float64. Each `map` task sums ≤5 files into a partial `(sum_vector,
count)`; each `reduce` task sums 2–5 partials; `finalize` divides by F once. The reduction tree
required by DM-001 *is* the pairwise-summation structure.

**Pros:**
- Error bound **O(log₅ F · ε)**: depth is 1 leaf level (≤5 addends) + ~7 reduce levels ≈ 8, so
  ~8 × 1.11e-16 ≈ **8.9 × 10⁻¹⁶** relative — comfortably inside the 1e-15 target, the *same*
  O(log n · ε) character as `numpy.mean`'s own internal pairwise reduction (so distributing
  costs nothing in accuracy), and ~10⁴× tighter than a naive serial accumulator.
- **Free.** Zero extra flops, zero extra memory, zero extra code versus the topology we already
  chose for scheduling reasons. The best kind of numerical improvement.
- Accumulators stay small: a leaf sums ≤5 addends (max 5.0), so no accumulator ever grows large
  relative to its addends and the systematic late-addend drift of the serial loop never occurs.
- One division, at the very end, on an exact integer F — a single rounding event for the whole
  pipeline instead of F of them.
- Vectorises: each task is `numpy` array addition over C = 1M elements, one pass, no
  per-element Python.

**Cons:**
- **Not bit-reproducible** across runs, because eager pairing (D3) varies the tree shape and
  float addition is non-associative. Results agree to ~1e-15, which is not the same as
  agreeing exactly — and anyone who diffs two output files will notice.
- Harder to reason about "what exactly was added when" during debugging; the reduction history
  is in the `partials` lineage rather than in a loop.
- The bound is *O(depth)*, so it degrades if the tree ever becomes lopsided (e.g. a long chain
  of fan-in-2 drains in a pathological tail).
- Gives no protection at all if the value bounds change — it is a bound-dependent argument, and
  its safety must be re-derived, not assumed, if [0, 1) changes.

### Kahan / Neumaier compensated summation inside workers

Carry a running compensation term alongside each accumulator, recovering the low-order bits
lost at each addition.

**Pros:**
- Error bound becomes **O(ε)** — effectively independent of n. The strongest practical bound
  short of exact arithmetic.
- Robust to *any* value distribution, including catastrophic cancellation and wide dynamic
  range, which is precisely where our bound-dependent argument stops holding.
- Well understood, no new dependencies, and pairs with the tree rather than replacing it.
- Genuinely the correct choice for a general-purpose numerics library, which is why it must be
  named rather than dismissed.

**Cons:**
- **Solves a problem we do not have.** The tree already delivers ~8.9e-16 relative; Kahan would
  take that to ~1e-16 — an improvement below the precision at which the CSV result is
  meaningfully consumed and far below any plausible tolerance for a mean of random numbers.
- **Doubles memory per accumulator**: a second C-length compensation vector is another 8 MB per
  in-flight vector, and it must either be serialised with every partial (making partials 16 MB,
  doubling the ~160 GB of level-0 traffic) or discarded at task boundaries — and discarding it
  at every boundary destroys most of the benefit in a distributed tree.
- **~4× the flops per addition**, and it defeats vectorisation: a correct Kahan loop resists
  the single-pass `numpy` add, so the real slowdown exceeds the flop count. Compilers may also
  reassociate operations in ways that silently void the compensation, so it needs a test that
  actually detects breakage — real complexity for no measurable gain here.

### Exact accumulation: fixed-point integers or Python arbitrary-precision

Eliminate rounding entirely. Either (a) scale each value to an integer (e.g. multiply by 2⁵³,
sum in a wide integer type) or (b) sum with Python's unbounded `int` / `fractions.Fraction`,
converting to float only at `finalize`.

**Pros:**
- **Exactly zero** summation error; the only rounding in the whole system is the final
  divide-and-cast. The sum is provably order-independent.
- Therefore **perfectly bit-reproducible** regardless of tree shape — it would remove the one
  real con of the chosen option.
- Fixed-point is a legitimate technique in ledger/financial systems and would be the right call
  if the mean fed anything requiring auditable exactness.
- Values in [0, 1) with a fixed scale factor are unusually well suited to it — a rare case
  where fixed-point is natural rather than forced.

**Cons:**
- **int64 overflows.** Scaling by 2⁵³ and summing 100k of them reaches ~9 × 10²⁰, past int64's
  9.22 × 10¹⁸ ceiling. Correctness needs int128 or Python bigints, so the natural type does not
  fit and the workaround is the expensive one.
- **Python bigint kills vectorisation.** C = 1M means 1M Python objects per vector instead of
  one 8 MB `numpy` buffer — one to two orders of magnitude slower and vastly more memory,
  turning a bounded 8 MB working set into an unpredictable one. `Fraction` is worse again
  (denominators grow without bound).
- Partials stop being fixed-width, so the raw-float64 blob format (D6) and its 8 MB size
  guarantee are gone; the brief's whole storage sizing would have to be redone.
- Buys precision **below what the input justifies** — exact summation of pseudorandom float64
  inputs is precision theatre. And shrinking the scale factor to make int64 fit (e.g. 2³⁰)
  reintroduces quantisation error, making it strictly worse than float64 + tree.

### Mixed precision: float32 partials with a float64 accumulator

Store and transmit partials as float32 to halve intermediate bandwidth, accumulating in float64
inside each task.

**Pros:**
- Halves partial size (8 MB → 4 MB) and hence the ~160 GB of level-0 intermediate traffic — a
  direct attack on DM-001's main acknowledged cost.
- Common, respectable practice in ML pipelines; the accumulate-wide/store-narrow split is a
  well-trodden pattern.
- Would make the object-store and network budget noticeably cheaper at the max job.

**Cons:**
- float32 has ~7 decimal digits (ε ≈ 1.19e-7). Rounding a partial to float32 **at every one of
  ~7 levels** injects ~1e-7 relative error per level — worst-case ~1e-6 overall, **nine orders
  of magnitude worse** than the target and worse than the naive serial float64 baseline it was
  meant to improve on.
- Also caps the *sum* magnitude: float32 loses integer exactness above 2²⁴ ≈ 1.68 × 10⁷, so
  large-count partials quantise.
- Trades the one property the system exists to get right (a correct mean) for a bandwidth win
  that in-worker pre-combining (DM-001 failure condition #1) delivers without any precision
  cost. Strictly dominated.

---

## Chosen: float64 accumulation, `(sum, count)` partials, division once in `finalize` — with the 5-ary reduction tree as pairwise summation

**The decision.** All accumulation is IEEE-754 **float64** (`numpy.float64`, C-contiguous
vectors of length C). A **partial** carries `(sum_vector, count)` where `count` is an exact
integer; partials are stored as raw little-endian float64 (D6), so no precision is lost in
transit. The **only** division in the system is in `finalize`: `mean = sum_vector / F`, executed
once, after the completion test `count == F` passes. No compensated summation, no fixed-point,
no reduced precision.

**Positive case:**

1. **The bounds make float64 unambiguously sufficient, and the argument is quantitative rather
   than a shrug.** Values are uniform [0, 1) (D9), so the maximum possible sum at any index is
   **< F ≤ 100k**, versus float64's exact-integer ceiling **2⁵³ ≈ 9.007 × 10¹⁵** — an ~11-order
   margin. There is no overflow path and no precision cliff anywhere in the stated envelope.
   Around a magnitude of 10⁵ the ulp is ~1.5 × 10⁻¹¹ absolute, and each addend is O(1), so
   every addition remains well-conditioned.

2. **`(sum, count)` is the correctness invariant, not merely a convenience** (D2, and the
   central argument of DM-001). Sums are associative and commutative, so any worker may combine
   any partials in any order. Means are not: with F = 12 and K = 5 the groups are 5, 5, 2, and
   mean-of-means silently reports 0.3333 where the truth is 0.1667. Under D3's adaptive fan-in,
   groups of 2–4 occur in drain mode *even when F is a multiple of 5*, so unequal group sizes
   are the normal case. Dividing exactly once, by an exact integer F, also means the entire
   pipeline contains **one** division-rounding event instead of F of them.

3. **Distribution is accuracy-*neutral*, and the naive serial loop is the only thing that
   loses — this is the point worth making precisely, because the tempting version of it is
   wrong.** The common intuition is "distribution introduces error." It
   does not. But the honest correction is *not* "we beat numpy": `numpy.mean` /
   `numpy.add.reduce` already sum **pairwise** internally, so a single-node numpy baseline
   carries the same **O(log n · ε)** bound our 5-ary tree does. Our tree is pairwise
   summation with base 5, so it has the *same character* as the oracle it is validated
   against — which is the real claim: **we can shard for throughput without paying anything
   in accuracy.** The **O(F·ε)** figure belongs only to a hand-written naive serial
   accumulator, and both the tree and numpy beat that by ~10⁴, which is exactly why nobody
   should ever write one. At F = 100k:

   | Shape | Depth / n | Worst-case relative error bound |
   |---|---|---|
   | Naive serial float64 loop, single node | n = 100,000 | ~100,000 · ε ≈ **1.1 × 10⁻¹¹** |
   | `numpy.mean` on one node (internally pairwise) | ~log₂ n | ~O(log n) · ε ≈ **1e-15 scale** |
   | Our 5-ary tree (1 leaf level + ~7 reduce levels) | ~8 | ~8 · ε ≈ **8.9 × 10⁻¹⁶** |

   The precise claim is therefore *"distribution is accuracy-neutral and the
   naive baseline is the only thing that loses"* — **not** *"we beat numpy."* The tree is
   free either way: it was already mandated by the K = 5 fan-in constraint (a partial is
   file-shaped at 8 MB, so reduces are limited to 5 inputs too, forcing ⌈log₅ 20,000⌉ = 7
   levels over ≈5,000 reduce tasks), and it happens to inherit the good error bound rather
   than sacrificing one. The mechanism is intuitive once stated, and it is the same mechanism
   numpy exploits: in the naive loop the accumulator grows to ~100k while each addend stays
   O(1), so late addends are added at a coarse ulp and are systematically under-weighted. In
   a tree — ours or numpy's — every addition combines two operands of *comparable* magnitude,
   which is the regime float64 handles best. Sharding for throughput and summing accurately
   point the same way, which is the pleasant part.

4. **Nothing float-valued gates control flow.** The completion test is `count == F` on integers
   (DM-001), retries are keyed on task ids (DM-006), and fan-in decisions count rows (DM-002).
   Floats appear only in the payload, so no float comparison can ever mis-decide whether a job
   is done.

**Why each alternative was rejected, specifically:**

- **Naive serial float64 (single node):** rejected primarily because it is architecturally
  unavailable — it is the central-accumulator design DM-001 rejected on ~160 GB through one
  NIC. Numerically it is also the *worse* option (~1.1e-11 vs ~8.9e-16 worst case), which is
  the point of item 3 above — noting that this penalty is specific to the hand-written naive
  loop, not to single-node computation as such, since `numpy.mean` on one node is already
  pairwise and lands at the tree's bound. The **test oracle** at small F is that numpy path,
  not the naive loop.
- **Kahan / Neumaier:** rejected because at these bounds it buys ~8.9e-16 → ~1e-16, an
  improvement below any tolerance that consumes this result, while doubling accumulator memory
  (a second 8 MB compensation vector per in-flight vector, which either doubles partial size to
  16 MB and the ~160 GB of level-0 traffic, or is discarded at task boundaries and stops
  helping), costing ~4× the flops per add, and defeating the single-pass `numpy` vectorisation.
  **Named explicitly as the mitigation of record** if the bounds grow (see failure conditions
  1 and 2) — it composes with the tree rather than replacing it, so adopting it later is
  additive, not a rewrite.
- **Exact integer / fixed-point / Python arbitrary precision:** rejected because int64
  overflows (100k × 2⁵³ ≈ 9 × 10²⁰ > 9.22 × 10¹⁸), so exactness requires int128 or Python
  bigints; bigints replace one 8 MB `numpy` buffer with 1M Python objects per vector — one to
  two orders of magnitude slower — and destroy the fixed-width partial format that D6's 8 MB
  sizing depends on. It would also be exact summation of pseudorandom approximate inputs.
  Retained as the answer if exactness ever becomes a *requirement* rather than a preference.
- **float32 partials:** rejected as strictly dominated — ~1e-7 relative error injected at each
  of ~7 levels is worse than the serial baseline it aimed to beat, for a bandwidth win that
  in-worker pre-combining (DM-001 failure condition #1) provides at zero precision cost.

**Failure condition.** Revisit if any of the following holds:

1. **Value bounds widen beyond [0, 1) — specifically, mixed signs or a dynamic range above
   ~10⁶.** Then catastrophic cancellation becomes reachable and the bound-dependent argument
   collapses. Mitigation: adopt **Neumaier (improved Kahan)** compensated summation in `map`
   and `reduce`, keeping the tree; carry the compensation term in the partial blob and accept
   16 MB partials.
2. **F cap raised above ~10⁹.** The tree bound stays comfortable (log₅ 10⁹ ≈ 13, so ~1.4e-15),
   but the *sum* magnitude approaches 10⁹ and the F/ε headroom argument must be re-derived
   rather than assumed. Recheck against 2⁵³ before raising the cap.
3. **Bit-identical output across runs becomes a requirement** (e.g. a regression harness that
   diffs result files byte-for-byte). Eager pairing (D3) makes the tree shape nondeterministic
   and float addition non-associative, so ~1e-15 agreement is the guarantee, not equality.
   Mitigation, in increasing cost: (a) canonicalise the tree — order reduce inputs by partial
   id and disable drain-mode fan-in, restoring determinism at a straggler-latency cost; or
   (b) move to fixed-point accumulation, which makes order irrelevant.
4. **Measured max relative error vs the numpy oracle exceeds 1e-14 at any F** in the scale
   suite. That indicates a lopsided tree (a long fan-in-2 drain chain) or a genuine bug in
   partial handling — investigate the tree depth distribution before touching the arithmetic.
5. **Any float-valued value ever gates control flow** (e.g. a completion check comparing a
   float count). That is a design-guard violation, not a tuning issue; fix the call site.

---

## Success Metrics

| Checkpoint | Target | How measured |
|-----------|--------|--------------|
| Accuracy vs single-node oracle | Max relative error ≤ **1e-15** across all C indices | Compare `finalize` output to `numpy.mean(axis=0)` on F ≤ 1000 fixtures |
| Unequal-group correctness | F = 12 fixture (ten 0.0 files, two 1.0 files) → exactly 1/6; mean-of-means would give 1/3 | Integration test asserting `abs(result - 1/6) < 1e-15` |
| Distribution is accuracy-neutral vs numpy; both beat the naive loop | Against a `math.fsum` / exact reference on an adversarial fixture (F = 100k of ~1e-9 addends): tree error ≈ single-node `numpy.mean` error (same order, no systematic loss from distributing), and **both** ≥10³× closer than a deliberately naive serial float64 loop over the same data | Dedicated numerics test comparing all four: exact reference, tree, `numpy.mean`, naive loop |
| No overflow / no inf / no nan | Zero non-finite values in any partial or result, at every F in the scale suite | Assertion in `reduce` and `finalize` on `numpy.isfinite().all()` |
| Sum-magnitude headroom | Max observed `sum` element < 1e5, i.e. < 2⁵³ / 10¹⁰ | Max-value counter recorded per `finalize` in the `events` log (D11) |
| Single division | Exactly one division per job (in `finalize`); zero divisions in `map` / `reduce` | Static check + code review; grep-level design-guard on worker modules |
| Integer-only completion logic | `count` typed `BIGINT` / Python `int` end to end; zero float comparisons in completion or fan-in code paths | Type assertions + design-guard test |
| Storage round-trip is lossless | Partial written then re-read is bit-identical (raw float64, D6) | Property test over random C-length vectors |
| Reproducibility characterisation | Two runs of the same job agree to ≤ 1e-15 (documented as *not* bit-identical) | Repeat-run diff recorded in the numerics test output |
