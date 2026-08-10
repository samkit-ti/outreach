/**
 * Job repository — T1 (LLD §4) and the read models behind GET /jobs, GET /jobs/:id.
 */
import type pg from 'pg';
import { config } from './../config.js';
import { pool, withTransaction } from './../db.js';
import { conflict, internal, tooManyRequests } from './../errors.js';
import type { JobRow, JobStatus, JobView, TaskCounts, TaskPayload } from './../types.js';
import { TASK_PRIORITY } from './../types.js';

/** Non-terminal job states — what MAX_ACTIVE_JOBS admission control counts. */
const ACTIVE_STATUSES: readonly JobStatus[] = ['pending', 'running', 'finalizing'];

/**
 * Postgres caps a statement at 65535 bound parameters. The map insert uses `unnest` on a
 * single jsonb[] param so row count is not param-bound, but we still batch to keep any
 * one statement's payload modest (20,000 rows ≈ <20 MB of JSONB at the max job, LLD §4 T1).
 */
const MAP_INSERT_BATCH = 2000;

export interface SubmitResult {
  jobId: string;
  /** true when the Idempotency-Key matched an existing job: 200, not 202 (LLD §4 T1). */
  existing: boolean;
  mapTaskCount: number;
}

/**
 * T1 — job submission. One transaction: job row + ALL ⌈F/K_FANIN⌉ map tasks +
 * `job.submitted` event, then `status='running'`. A transaction either commits every map
 * row or none, which is why no `dedupe_key` exists (LLD §1/§2): a duplicate map task is
 * unrepresentable.
 *
 * Range/allow-list/duplicate/size validation has already run at the edge (validation.ts);
 * this function owns only the admission-control count and the transaction.
 */
export async function submitJob(params: {
  f: number;
  c: number;
  inputUris: readonly string[];
  idempotencyKey: string | null;
}): Promise<SubmitResult> {
  const { f, c, inputUris, idempotencyKey } = params;

  return withTransaction(async (client) => {
    // Idempotency fast path: a retried POST returns the original job, never a twin, and
    // is never rejected by admission control — it creates no new work.
    if (idempotencyKey !== null) {
      const prior = await client.query<{ id: string }>(
        'SELECT id FROM jobs WHERE idempotency_key = $1',
        [idempotencyKey],
      );
      if (prior.rows.length > 0) {
        return { jobId: prior.rows[0]!.id, existing: true, mapTaskCount: 0 };
      }
    }

    // 429 + Retry-After if active ≥ MAX_ACTIVE_JOBS (LLD §4 T1). Checked before any write.
    const active = await client.query<{ n: string }>(
      'SELECT count(*)::text AS n FROM jobs WHERE status = ANY($1::job_status[])',
      [ACTIVE_STATUSES],
    );
    const activeCount = Number(active.rows[0]?.n ?? '0');
    if (activeCount >= config.maxActiveJobs) {
      throw tooManyRequests(
        'too_many_active_jobs',
        `at most ${config.maxActiveJobs} active jobs may exist concurrently`,
        config.retryAfterSeconds,
        { active: activeCount, limit: config.maxActiveJobs },
      );
    }

    // `ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL`: the index in
    // LLD §1 is *partial*, and Postgres only infers a partial unique index as the
    // arbiter when the index predicate is restated here. Semantics are the LLD's:
    // absent header ⇒ NULL ⇒ never conflicts ⇒ a distinct job by design.
    const inserted = await client.query<{ id: string }>(
      `INSERT INTO jobs (f, c, idempotency_key) VALUES ($1, $2, $3)
         ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
         RETURNING id`,
      [f, c, idempotencyKey],
    );

    if (inserted.rows.length === 0) {
      // The key already exists — written by a concurrent request whose id we never saw,
      // so we must *select* it, not infer it (LLD §4 T1).
      if (idempotencyKey === null) {
        throw internal('job insert returned no row and no idempotency key was supplied');
      }
      const original = await client.query<{ id: string }>(
        'SELECT id FROM jobs WHERE idempotency_key = $1',
        [idempotencyKey],
      );
      if (original.rows.length === 0) {
        throw conflict('idempotency_race', 'conflicting job disappeared; retry the request', {
          idempotencyKey,
        });
      }
      return { jobId: original.rows[0]!.id, existing: true, mapTaskCount: 0 };
    }

    const jobId = inserted.rows[0]!.id;

    // ALL map tasks, now: slice inputUris into ⌈F/K_FANIN⌉ contiguous chunks in LIST ORDER.
    const payloads = chunkInputUris(jobId, c, inputUris);
    await insertMapTasks(client, jobId, payloads);

    await client.query(`UPDATE jobs SET status = 'running' WHERE id = $1`, [jobId]);

    await client.query(
      `INSERT INTO events (type, job_id, payload) VALUES ('job.submitted', $1, $2::jsonb)`,
      [jobId, JSON.stringify({ f, c, mapTasks: payloads.length, kFanin: config.kFanin })],
    );

    return { jobId, existing: false, mapTaskCount: payloads.length };
  });
}

/**
 * LLD §2: T1 slices the submitted `inputUris[]` into ⌈F/K_FANIN⌉ contiguous K_FANIN-sized
 * chunks **in list order**, so the mapping from submitted list to map tasks is total and
 * disjoint. A map task's `inputUris` *are* its identity.
 */
export function chunkInputUris(
  jobId: string,
  c: number,
  inputUris: readonly string[],
): TaskPayload[] {
  const out: TaskPayload[] = [];
  for (let i = 0; i < inputUris.length; i += config.kFanin) {
    out.push({
      kind: 'map',
      jobId,
      c,
      inputUris: inputUris.slice(i, i + config.kFanin) as string[],
    });
  }
  return out;
}

async function insertMapTasks(
  client: pg.PoolClient,
  jobId: string,
  payloads: readonly TaskPayload[],
): Promise<void> {
  // priority=2 for map (LLD §1: the DDL CHECK makes priority a function of type).
  const sql = `INSERT INTO tasks (job_id, type, priority, payload)
               SELECT $1::uuid, 'map'::task_type, $2::smallint, p
               FROM unnest($3::jsonb[]) AS p`;
  for (let i = 0; i < payloads.length; i += MAP_INSERT_BATCH) {
    const batch = payloads.slice(i, i + MAP_INSERT_BATCH).map((p) => JSON.stringify(p));
    await client.query(sql, [jobId, TASK_PRIORITY.map, batch]);
  }
}

// ---------------------------------------------------------------------------
// Read models
// ---------------------------------------------------------------------------

/**
 * `R_est` — the analytic count of partials an ideal K-ary tree *consumes* (DM-009):
 * every partial in the tree except the root, i.e. L·k/(k−1) − 1 with L = ⌈F/k⌉ leaves.
 * It is a pure function of F, so it needs no column: the DDL is the LLD's verbatim and
 * stores nothing derivable.
 */
export function rEst(f: number): number {
  const k = config.kFanin;
  const leaves = Math.ceil(f / k);
  return Math.max(0, (leaves * k) / (k - 1) - 1);
}

/**
 * Progress = (mapped_files + reduce_inputs_consumed) / (F + R_est), clamped at 99% until
 * `finalize` commits — only finalize writes 100% (LLD §6, DM-009). Both numerator terms
 * are state-derived and monotone, so retries cannot double-count.
 */
export function computeProgress(args: {
  status: JobStatus;
  f: number;
  mappedFiles: number;
  reduceInputsConsumed: number;
}): number {
  if (args.status === 'completed') return 1;
  const denom = args.f + rEst(args.f);
  if (denom <= 0) return 0;
  const raw = (args.mappedFiles + args.reduceInputsConsumed) / denom;
  return Math.min(0.99, Math.max(0, Number(raw.toFixed(4))));
}

interface JobAggregateRow extends JobRow {
  n_pending: string;
  n_claimed: string;
  n_done: string;
  n_dead: string;
  mapped_files: string;
  reduce_inputs_consumed: string;
}

/**
 * One query serves both GET /jobs and GET /jobs/:id: job row + task counts by status +
 * the two coverage terms. `mapped_files` is Σ count over *map-produced* partials, hence
 * the join back to `tasks`.
 */
const JOB_AGGREGATE_SELECT = `
  SELECT j.*,
         COALESCE(tc.n_pending, 0)::text AS n_pending,
         COALESCE(tc.n_claimed, 0)::text AS n_claimed,
         COALESCE(tc.n_done, 0)::text    AS n_done,
         COALESCE(tc.n_dead, 0)::text    AS n_dead,
         COALESCE(pc.mapped_files, 0)::text AS mapped_files,
         COALESCE(pc.consumed, 0)::text     AS reduce_inputs_consumed
  FROM jobs j
  LEFT JOIN (
    SELECT job_id,
           count(*) FILTER (WHERE status = 'pending') AS n_pending,
           count(*) FILTER (WHERE status = 'claimed') AS n_claimed,
           count(*) FILTER (WHERE status = 'done')    AS n_done,
           count(*) FILTER (WHERE status = 'dead')    AS n_dead
    FROM tasks GROUP BY job_id
  ) tc ON tc.job_id = j.id
  LEFT JOIN (
    SELECT p.job_id,
           COALESCE(SUM(p.count) FILTER (WHERE pt.type = 'map'), 0) AS mapped_files,
           count(*) FILTER (WHERE p.consumed_by IS NOT NULL)        AS consumed
    FROM partials p JOIN tasks pt ON pt.id = p.produced_by
    GROUP BY p.job_id
  ) pc ON pc.job_id = j.id`;

function toView(row: JobAggregateRow): JobView {
  const counts: TaskCounts = {
    pending: Number(row.n_pending),
    claimed: Number(row.n_claimed),
    done: Number(row.n_done),
    dead: Number(row.n_dead),
  };
  return {
    id: row.id,
    f: row.f,
    c: row.c,
    status: row.status,
    progress: computeProgress({
      status: row.status,
      f: row.f,
      mappedFiles: Number(row.mapped_files),
      reduceInputsConsumed: Number(row.reduce_inputs_consumed),
    }),
    counts,
    resultUri: row.result_uri,
    error: row.error,
    createdAt: row.created_at.toISOString(),
    completedAt: row.completed_at === null ? null : row.completed_at.toISOString(),
  };
}

export async function getJobView(jobId: string): Promise<JobView | null> {
  const { rows } = await pool.query<JobAggregateRow>(`${JOB_AGGREGATE_SELECT} WHERE j.id = $1`, [
    jobId,
  ]);
  const row = rows[0];
  return row === undefined ? null : toView(row);
}

export async function getJobRow(jobId: string): Promise<JobRow | null> {
  const { rows } = await pool.query<JobRow>('SELECT * FROM jobs WHERE id = $1', [jobId]);
  return rows[0] ?? null;
}

export interface Cursor {
  createdAt: string;
  id: string;
}

/** Keyset cursor on (created_at, id) — opaque base64url to the client. */
export function encodeCursor(c: Cursor): string {
  return Buffer.from(`${c.createdAt}|${c.id}`, 'utf8').toString('base64url');
}

export function decodeCursor(raw: string): Cursor | null {
  try {
    const decoded = Buffer.from(raw, 'base64url').toString('utf8');
    const sep = decoded.lastIndexOf('|');
    if (sep <= 0) return null;
    const createdAt = decoded.slice(0, sep);
    const id = decoded.slice(sep + 1);
    if (Number.isNaN(Date.parse(createdAt)) || id.length === 0) return null;
    return { createdAt, id };
  } catch {
    return null;
  }
}

export interface JobPage {
  jobs: JobView[];
  nextCursor: string | null;
}

/**
 * Keyset pagination on `(created_at, id)`, newest first. Strictly-less-than on the tuple
 * is what makes it a keyset scan rather than an OFFSET walk, and it is stable under
 * concurrent inserts (a new job appears on page 1, never shifting page 2).
 */
export async function listJobs(limit: number, cursor: Cursor | null): Promise<JobPage> {
  const where = cursor === null ? '' : ' WHERE (j.created_at, j.id) < ($2::timestamptz, $3::uuid)';
  const params: unknown[] = cursor === null ? [limit + 1] : [limit + 1, cursor.createdAt, cursor.id];

  const { rows } = await pool.query<JobAggregateRow>(
    `${JOB_AGGREGATE_SELECT}${where} ORDER BY j.created_at DESC, j.id DESC LIMIT $1`,
    params,
  );

  const hasMore = rows.length > limit;
  const page = hasMore ? rows.slice(0, limit) : rows;
  const last = page[page.length - 1];

  return {
    jobs: page.map(toView),
    nextCursor:
      hasMore && last !== undefined
        ? encodeCursor({ createdAt: last.created_at.toISOString(), id: last.id })
        : null,
  };
}
