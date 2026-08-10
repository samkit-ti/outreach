/**
 * System-level reads: the stats payload (GET /system/stats and the SSE snapshot
 * frame share it, DM-009), the events tail, and desired_workers config.
 */
import { pool } from '../db.js';
import { config } from '../config.js';
import type { EventRow, SystemStats, TaskStatus, TaskType } from '../types.js';

const ZERO_STATUS: Record<TaskStatus, number> = { pending: 0, claimed: 0, done: 0, dead: 0 };
const ZERO_TYPE: Record<TaskType, number> = { map: 0, reduce: 0, finalize: 0 };

export async function getDesiredWorkers(): Promise<number> {
  const res = await pool.query<{ value: unknown }>(
    `SELECT value FROM system_config WHERE key = 'desired_workers'`,
  );
  if (res.rows.length === 0) return config.desiredWorkersSeed;
  const value = res.rows[0]!.value;
  if (typeof value === 'number') return value;
  if (value !== null && typeof value === 'object' && 'desired' in (value as object)) {
    const d = (value as { desired: unknown }).desired;
    if (typeof d === 'number') return d;
  }
  return config.desiredWorkersSeed;
}

export async function setDesiredWorkers(desired: number): Promise<void> {
  await pool.query(
    `INSERT INTO system_config (key, value) VALUES ('desired_workers', $1::jsonb)
     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
    [JSON.stringify({ desired })],
  );
  await pool.query(
    `INSERT INTO events (type, payload) VALUES ('config.desired_workers_changed', $1::jsonb)`,
    [JSON.stringify({ desired })],
  );
}

/** Seed the row on boot so the supervisor always has something to reconcile to. */
export async function seedDesiredWorkers(): Promise<void> {
  await pool.query(
    `INSERT INTO system_config (key, value) VALUES ('desired_workers', $1::jsonb)
     ON CONFLICT (key) DO NOTHING`,
    [JSON.stringify({ desired: config.desiredWorkersSeed })],
  );
}

export async function getSystemStats(): Promise<SystemStats> {
  const [workers, jobs, tasks, pendingTasks, throughput, ages, desired] = await Promise.all([
    pool.query<{ status: string; n: string }>(
      `SELECT status, count(*)::text AS n
       FROM workers
       WHERE last_heartbeat > now() - make_interval(secs => $1)
       GROUP BY status`,
      [config.workerAliveSeconds],
    ),
    pool.query<{ status: string; queued: string; n: string }>(
      `SELECT j.status,
              count(*) FILTER (
                WHERE j.status = 'running'
                  AND EXISTS (SELECT 1 FROM tasks t WHERE t.job_id = j.id AND t.status = 'pending')
                  AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.job_id = j.id AND t.status = 'claimed')
              )::text AS queued,
              count(*)::text AS n
       FROM jobs j GROUP BY j.status`,
    ),
    pool.query<{ status: string; type: string; n: string }>(
      `SELECT status, type, count(*)::text AS n FROM tasks GROUP BY status, type`,
    ),
    pool.query<{ type: string; n: string }>(
      `SELECT type, count(*)::text AS n FROM tasks WHERE status = 'pending' GROUP BY type`,
    ),
    pool.query<{ n: string }>(
      `SELECT count(*)::text AS n FROM events
       WHERE type = 'task.done' AND ts > now() - interval '10 seconds'`,
    ),
    pool.query<{ oldest_pending: number | null; oldest_claimed: number | null }>(
      `SELECT
         (SELECT extract(epoch FROM now() - min(created_at)) FROM tasks WHERE status = 'pending')::float8 AS oldest_pending,
         (SELECT extract(epoch FROM now() - min(claimed_at)) FROM tasks WHERE status = 'claimed')::float8 AS oldest_claimed`,
    ),
    getDesiredWorkers(),
  ]);

  const workerCounts = { alive: 0, busy: 0, idle: 0, draining: 0 };
  for (const row of workers.rows) {
    const n = Number(row.n);
    workerCounts.alive += n;
    if (row.status === 'busy') workerCounts.busy += n;
    else if (row.status === 'draining') workerCounts.draining += n;
    else workerCounts.idle += n;
  }

  const jobCounts = { queued: 0, running: 0, completed: 0, failed: 0, pending: 0, finalizing: 0 };
  for (const row of jobs.rows) {
    const n = Number(row.n);
    if (row.status in jobCounts) {
      (jobCounts as Record<string, number>)[row.status] += n;
    }
    if (row.status === 'running') jobCounts.queued += Number(row.queued);
  }
  // "queued" jobs are a subset of running (LLD §6); report running as the rest.
  jobCounts.running -= jobCounts.queued;

  const byStatus = { ...ZERO_STATUS };
  const byType = { ...ZERO_TYPE };
  for (const row of tasks.rows) {
    byStatus[row.status as TaskStatus] += Number(row.n);
    byType[row.type as TaskType] += Number(row.n);
  }
  const pendingByType = { ...ZERO_TYPE };
  for (const row of pendingTasks.rows) pendingByType[row.type as TaskType] = Number(row.n);

  return {
    workers: { desired, ...workerCounts },
    jobs: jobCounts,
    tasks: { byStatus, byType, pendingByType },
    throughput: { tasksPerSec: Number(throughput.rows[0]!.n) / 10, windowSeconds: 10 },
    oldest_pending_age_sec: ages.rows[0]!.oldest_pending,
    oldest_claimed_age_sec: ages.rows[0]!.oldest_claimed,
  };
}

/**
 * The SSE tail (DM-009): ids are BIGSERIAL — assigned in order, visible in COMMIT
 * order — so the tail reads one second behind `now()`. That lag IS the resume
 * guarantee: nothing older than the visibility horizon can still be uncommitted.
 */
export async function readEventsAfter(cursor: number): Promise<EventRow[]> {
  const res = await pool.query<EventRow>(
    `SELECT id, ts, type, job_id, task_id, worker_id, payload
     FROM events
     WHERE id > $1 AND ts < now() - interval '1 second'
     ORDER BY id
     LIMIT $2`,
    [cursor, config.sse.tailBatch],
  );
  return res.rows;
}
