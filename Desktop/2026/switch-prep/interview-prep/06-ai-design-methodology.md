# Designing Systems AI-First — The Playbook, and the Questions That Matter

Two parts. Part 1: the step-by-step method for designing any system with AI (distilled
from what actually worked here, including the mistakes). Part 2: the evaluation
questions to ask of every component and decision — the basic battery, then the
philosophical ones.

---

# Part 1 — The AI-first design playbook

**The one-line thesis:** AI gives you unlimited breadth, tireless tracing, and honest
adversaries on demand. You supply judgment, scope, and the refusal to accept any claim
without a number or a trace. Design quality comes from the *sequence*, not the model.

### Step 0 — Frame before generating. Forbid design.

Paste the brief verbatim into the record. Make the AI restate the problem, extract
requirements, and — critically — extract the *stated purpose* of every constraint
("to simulate RAM limits", "I'm most interested in how you combine results").
Do not let it propose a design yet. AI asked to "design a system" produces a plausible
average of the internet; AI asked to "tell me what this problem *is*" produces insight.

### Step 1 — Hunt the invariants (the discoveries phase).

Ask directly: *what algebraic structure does this computation have? what objects are
secretly the same shape? what is conserved?* Here that surfaced "sums are a
commutative monoid" and "a partial is file-shaped" — two observations that determined
everything, and that no amount of component-picking would ever have found. Decisions
made before the invariants are known are guesses wearing suits.

### Step 2 — Envelope math before any choice.

Compute the extremes: sizes, counts, rates, the byte flows. (Here: 8 MB partials, 25k
tasks, 800 GB, ≪1k claims/s.) Every later decision gets tested against these numbers;
without them, "will it scale" is vibes. Make the AI derive them and *you* check the
arithmetic — models drop factors of two without blushing.

### Step 3 — Draw the decision DAG, then decide in dependency order.

List the decision points, then ask: which depends on which? Decide upstream-first.
The famous inversion this produces: **infrastructure last, not first**. The queue
technology here was chosen by a requirement (consume+enqueue atomicity) that only
*emerged* after the scheduling and completion designs existed — choosing it on day
one, on generic grounds, is how the alternative treatment ended up patching a
job-hangs-forever hole with an outbox. Every deviation we made from dependency order
later cost a review finding; the correlation was 100%.

### Step 4 — One decision record at a time, with steelmanned alternatives.

For each decision: 3–6 real alternatives, and force the AI to make each one's *best*
case before killing it (the central accumulator was rejected on bandwidth only after
conceding memory was fine — the honest rejection is the defensible one). Demand two
outputs per decision: the concrete failure scenario of everything rejected, and the
**reversal trigger** for the thing chosen ("what measured condition would flip this?").
Write it down immediately — decision records written during design cost nothing;
reconstructed afterward they're fiction.

### Step 5 — Adversarial review with fresh eyes, at least two lenses.

Spin up *fresh contexts* (separate agents/sessions — a reviewer sharing your chat
history shares your blind spots) with different mandates: one traces correctness
(interleavings, crash windows, "does every column the SQL reads exist?"), one attacks
completeness and defensibility (unaddressed requirements, overclaims, missing
decisions). Here these passes found four blockers in a design that looked done —
including "no job can ever complete" on the happy path. Fix everything, keep a
ledger, re-verify. Self-review by the authoring context is worth ~30% of this.

### Step 6 — Cross-validate against an independent solution.

Have a *different* AI (or a cold session) solve the same problem from scratch, then
gap-analyze both directions: what did they think of that you didn't (here: the formal
chunk-size derivation), and what did you get that they missed (their self-admitted
"one genuine hole" was our headline argument). Independent convergence on the same
core is the strongest evidence available that the core is right.

### Step 7 — Freeze the contract, then build in parallel.

Only after review does code start. The low-level design becomes the *normative
contract*: exact schemas, exact transactions, exact payloads. Parallel agents each own
a **disjoint directory** and code against the contract, never against each other; one
agent owns the schema and everyone else quotes it. Rule learned the hard way: agents
faithfully implement your spec's bugs — which is precisely why Step 5 must precede
Step 7, and why "the spec compiled" is a real milestone.

### Step 8 — Black-box tests written from the docs, not the code.

The test author reads the design, not the implementation, and asserts through public
surfaces (HTTP, DB, storage). This catches the class of bug design review can't: our
suite found a URL signed against an unreachable hostname — true to spec, broken in
reality. Include the brief's own worked example as the first test; include a chaos
test; include one test that pins the nastiest interleaving from Step 5.

### Step 9 — Build artifacts that prove understanding.

A step-level trace of one job through everything; a simulator racing the chosen
design against its rejected alternatives; a visual atlas of the decision space.
These force a final honesty pass (you cannot animate a design you don't understand)
and become the assets you explain the system with.

### Step 10 — Know the division of labor, and keep it.

- **AI owns:** breadth (alternatives, prior art), tracing (interleavings, failure
  matrices), consistency sweeps, derivations, test generation, tireless iteration.
- **You own:** scope ("inputs pre-exist; drop generation"), judgment calls (the
  letter-vs-spirit reading of a constraint), priorities, and *verification gates* —
  nothing merges on the AI's say-so; everything passes a compile, a test, a render,
  or a grep.
- **Both:** every claim gets a number; every number gets a source; every fix gets
  re-verified. The moment you accept "should work," quality dies.

---

# Part 2 — The questions that design each component

## 2a. The universal battery — ask these of EVERY decision

1. **What exactly does this decide, in numbers?** Current state, target, and the
   quantity that makes it hard. (Not "handle scale" — "20,000 partials, fan-in 5.")
2. **What are the real alternatives, and what is each one's best argument?** If you
   can't argue *for* a rejected option, you haven't understood it — and someone who
   has will beat you with it.
3. **What is the chosen option's concrete failure scenario?** Inputs, interleaving,
   wrong outcome. "Might have issues" is not a scenario.
4. **What breaks first at 10×, and what's the written reversal trigger?** Every
   decision should carry the measured condition that would flip it.
5. **Where does this place correctness — in state or in events?** State can be
   re-read; events can be duplicated, lost, reordered. (The counter vs the count.)
6. **What happens when this runs twice? Crashes halfway? Arrives out of order?**
   The at-least-once trilogy. If any answer is "that can't happen," it happens.
7. **Who owns this at runtime, and what happens when the owner dies?** Every piece
   of state needs an owner and a survival story for the owner's death.
8. **What does this force downstream, and what upstream decision does it stand on?**
   (The atomicity requirement standing on eager pairing; the queue standing on the
   atomicity requirement.) A decision that can't name its dependencies is floating.
9. **What is the price, and is it written down?** Bytes, latency, components,
   complexity. Unpriced decisions read as unexamined.
10. **How would a black-box test prove it?** If no observable behavior distinguishes
    this choice from its alternative, question whether it's a decision at all.

## 2b. Per-component fundamentals

- **API / front door:** validate everything at the door (and know what you
  deliberately *don't* validate, and why); idempotent submission; stateless — could
  you kill any instance mid-request with zero job impact?
- **Queue / coordination:** delivery semantics named (at-least-once here); what must
  be *atomic with state changes* — this question alone picks the technology; fairness
  under multi-tenancy; what "empty" does and doesn't mean.
- **Workers / compute:** memory ceiling by construction, not hope; lease + fence +
  absolute deadline (crash, zombie, and wedged are three different failures); effects
  idempotent via deterministic naming; graceful shutdown optional, never load-bearing.
- **Storage / data plane:** control plane and data plane separated (references travel,
  bytes don't); deterministic keys as the idempotency mechanism; who may write where
  (blast-radius confinement); formats priced (nobody reads intermediates — don't pay
  text costs on them).
- **Completion / lifecycle:** proof over bookkeeping; exactly-once *actions* via CAS,
  not via hoping; a proven-complete result must be unkillable by retry accounting.
- **Observability:** metrics derived from state (monotone by construction) not
  accumulated from events; the one early-warning gauge (oldest-pending age); honest
  about what the stream can miss.

## 2c. The philosophical questions — ask these before and above everything

1. **What is the algebra of this problem?** Does the core operation merge? Associative,
   commutative, an identity? The answer determines whether coordination is optional
   (mean) or the whole problem (median). This is the first question, always.
2. **For each constraint: what is its letter, what is its spirit, and which reading
   keeps the problem meaningful?** A reading that makes the rule vacuous can't be the
   intended one. Choose the conservative reading; document it as a choice.
3. **Where does truth live?** One source; everything else is a cache and must be
   treated as one. Every bug class in this project traces to a second copy of truth.
4. **Prevent, or make harmless?** Exactly-once is prevention and it's a myth across
   system boundaries; idempotency is harmlessness and it's buildable. Prefer designs
   where the bad event is *allowed* and *neutralized*.
5. **Planned or emergent?** Bind decisions at the moment of maximum information —
   which is usually runtime, not submit time. (The tree discovered, not wired.)
6. **Forecast or sample?** Any design needing a prediction (push scheduling) pays for
   prediction error; a design that defers the decision until the fact is free (pull)
   pays nothing. Ask where you're secretly forecasting.
7. **What can't drift?** Filenames, transactions, conserved quantities, desired-state
   rows, uniqueness constraints. Move correctness into those. Anything that can drift
   eventually does — at 3 a.m.
8. **What is actually being evaluated / delivered?** The brief drew a boundary
   (components fixed, algorithm graded). Adopting Spark was rejected not because Spark
   is wrong but because it erases the deliverable. Know what the exercise *is*.
9. **Loud or silent?** Rank failure modes: wrong-and-silent is unacceptable, stuck-
   and-alarmed is fine, failed-and-explained is good. Design the failure direction.
10. **What is the smallest CORRECT system, and separately the smallest OPERABLE one?**
    Two different bars (bare minimum vs MVP); collapsing them hides which decisions
    are load-bearing for correctness versus for survival.
11. **What would change my mind?** If a decision has no conceivable reversal trigger,
    it wasn't reasoned to — it was assumed. Every record here ends with one, and that
    habit is the single cheapest upgrade to any design process.
