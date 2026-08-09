# Distributed Mean — Problem Statement (verbatim from prompt)

> Source: interviewer-provided Google Doc (`1sbcfM2Anu096MEdPb_qe6M_ScjVfTIk1F8F5GDlT7Q4`), captured 2026-08-09.

## Setting (context for this design — not part of the brief)

The underlying scenario is **federated-learning weight aggregation**: the F files are
model-weight vectors of C float64 values that **already exist** on distributed nodes,
exposed at S3-API URIs. The brief's random-number *generation* is therefore replaced by
**ingestion of pre-existing inputs** — `POST /jobs` takes an explicit `inputUris[]`
(F = list length) instead of generating anything. Everything else in the brief below —
the index-wise mean, the K=5 fan-in constraint, W workers, the queue, the aggregation
question — is unchanged, and the text that follows is verbatim.

## Summary

Design a system that assigns a large job to be processed across a fleet of workers. The workers' outputs are aggregated into a single result which is returned to the user.

The number of workers (W) are at the system level and not specific to a job. You're free to keep them constant in the application or add support for making them configurable (see Bonus).

The job itself will be to use the workers to compute the mean of every index across F files full of C random numbers.

- F = number of files. (1 < F < 100k)
- C = number of random values in each file (1 < C < 1000k)

### Example

If F=2 and C=3, and the input files are [1,2,3] and [4,5,6], the output is a single file of [2.5, 3.5, 4.5].

Values for F and C are chosen by the user. Random-number bounds are our choice (e.g. 0–1). File format is our choice (csv, etc).

## Components

- API: NodeJS, Express, TypeScript
- DB
- Queue: any kind (SQS, something local, anything)
- Fleet of workers: Python

## Flow

- W workers sit idle waiting for a job to appear on the queue.
- User creates a job via API call providing C and F.
- API enqueues the job; once at least one worker is available, processing starts.
- The result of each worker must be combined to create the final averaged file. ("I'm interested to see how you approach this.")

## Assumptions (given)

- To simulate RAM constraints, a worker cannot process more than 5 files at a time. The system must split the job when F > 5.
- Generated files can be stored on the API's local filesystem or a place of our choosing (e.g. a bucket), as long as workers can pull/read them.
- Workers process files at different speeds. Design the orchestration so workers spend as little time as possible idling or waiting on slower workers.

## Critical aspects being graded

1. For F > 5 (the jobs the interviewer is most interested in): one or multiple items may be placed on the queue — no strict 1:1 between job and queue item.
2. Efficiency of the task-distribution algorithm.
3. How the system decides a job is finished.
4. Support submitting multiple jobs while jobs are ongoing.

## Expectation

A complete working solution is desired but not the primary goal. The main interest is the design and how it addresses the critical aspects. A well-thought design doc + partial implementation is acceptable.

## Bonus

- Keep W configurable via the API.
- Create a UI with updating logs: workers free/busy, jobs completed, jobs queued, and anything else judged relevant.
