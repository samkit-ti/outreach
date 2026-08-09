# Research & Prior Art — Reading List (v1)

Grounding material for the trade-offs argued in the ITDs. Skim before the follow-up
discussion; each entry notes which decision it backs.

## Straggler mitigation (→ DM-002)

- **LATE paper** — Zaharia et al., *Improving MapReduce Performance in Heterogeneous
  Environments* (OSDI'08): https://www.usenix.org/legacyurl/improving-mapreduce-performance-heterogeneous-environments
  The canonical "workers run at different speeds" work: progress-rate estimation,
  speculative backup tasks. We cite it as the evolution path beyond pull-based balancing.
- Speculative execution in Hadoop (overview): https://techvidvan.com/tutorials/speculative-execution-in-hadoop/
- Survey of speculative-execution strategies in MapReduce: https://www.researchgate.net/publication/309559336_A_Survey_of_Speculative_Execution_Strategy_in_MapReduce
- Original MapReduce paper (Dean & Ghemawat, OSDI'04) — §3.6 "Backup Tasks".

## Fan-out/fan-in & completion detection (→ DM-001, DM-003)

- How Celery chord synchronization works (counter vs poll internals):
  https://blog.untrod.com/2015/03/how-celery-chord-synchronization-works.html
- The fanout pattern explained: https://www.better-simple.com/django/2023/12/06/fanout-pattern-explained/
- Fan-out/fan-in messaging pattern: https://www.sysdesai.com/learn/messaging-patterns/fan-out-fan-in

## Queue technology (→ DM-004)

- PostgreSQL `FOR UPDATE SKIP LOCKED` one-liner job queue: https://www.dbpro.app/blog/postgresql-skip-locked
- "Postgres is the only queue you need (until 50k jobs/sec)":
  https://medium.com/@harsh.vaghela.work/postgres-is-the-only-queue-you-need-until-50k-jobs-sec-5931611b551c
- Postgres as a queue vs Kafka/RabbitMQ: https://www.techplained.com/postgres-as-queue
- HN: "Choose Postgres queue technology" (counterarguments live here):
  https://news.ycombinator.com/item?id=37636841
- SQS: visibility timeout, 256 KB message cap, FIFO throughput limits — AWS docs.

## Numerics (→ DM-010)

- Pairwise summation (error O(log n · ε)): https://en.wikipedia.org/wiki/Pairwise_summation
- Numerically stable single-pass parallel statistics (combine-(sum,count,…) formulas):
  https://www.researchgate.net/publication/224605035_Numerically_stable_single-pass_parallel_statistics_algorithms
- Chan, Golub, LeVeque — updating formulae for combining sample statistics (the
  general form of our (Σ, n) merge).

## Adjacent systems worth name-dropping accurately

- **Hadoop/Spark tree aggregation** — `treeReduce`/`treeAggregate` exist precisely
  because flat reduce at the driver bottlenecks: our D1-C rejection in production form.
- **Celery chord** — the two-phase barrier we rejected (DM-001-b) as a library primitive.
- **MPI allreduce** — the HPC answer; assumes homogeneous, reliable nodes — exactly the
  assumptions this prompt withdraws (heterogeneous speeds, crash tolerance).
