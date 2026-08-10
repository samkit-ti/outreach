/**
 * Shared types. The task payload union is LLD §2 verbatim — mirrored by Python
 * dataclasses on the worker side. Only the `map` variant is constructed here (T1
 * creates every map task and nothing else; reduce/finalize are born in T2).
 */

export type TaskPayload =
  | { kind: 'map'; jobId: string; inputUris: string[] /* ≤5 */; c: number }
  | {
      kind: 'reduce';
      jobId: string;
      partialIds: string[] /* 2–5 */;
      partialUris: string[];
      c: number;
    }
  | { kind: 'finalize'; jobId: string; partialUri: string; f: number; c: number };

/** LLD §1 job_status enum. */
export type JobStatus = 'pending' | 'running' | 'finalizing' | 'completed' | 'failed';

/** LLD §1 task_status enum. There is no transient 'failed' — a retryable failure IS a requeue. */
export type TaskStatus = 'pending' | 'claimed' | 'done' | 'dead';

/** LLD §1 task_type enum. */
export type TaskType = 'map' | 'reduce' | 'finalize';

/**
 * LLD §1: priority is a function of type, not a free field — the DDL CHECK makes the
 * ASC/DESC footgun unrepresentable. This table mirrors it so the API can never insert
 * a row the CHECK would reject.
 */
export const TASK_PRIORITY: Readonly<Record<TaskType, number>> = {
  finalize: 0,
  reduce: 1,
  map: 2,
};

export interface JobRow {
  id: string;
  f: number;
  c: number;
  status: JobStatus;
  idempotency_key: string | null;
  result_uri: string | null;
  error: string | null;
  created_at: Date;
  completed_at: Date | null;
}

/** Per-job task counts by status (LLD §6 `counts`). */
export interface TaskCounts {
  pending: number;
  claimed: number;
  done: number;
  dead: number;
}

export interface JobView {
  id: string;
  f: number;
  c: number;
  status: JobStatus;
  progress: number;
  counts: TaskCounts;
  resultUri: string | null;
  error: string | null;
  createdAt: string;
  completedAt: string | null;
}

/** GET /system/stats and the 1 Hz SSE snapshot frame share this payload (DM-009). */
export interface SystemStats {
  workers: {
    desired: number;
    alive: number;
    busy: number;
    idle: number;
    draining: number;
  };
  jobs: {
    queued: number;
    running: number;
    completed: number;
    failed: number;
    pending: number;
    finalizing: number;
  };
  tasks: {
    byStatus: Record<TaskStatus, number>;
    byType: Record<TaskType, number>;
    pendingByType: Record<TaskType, number>;
  };
  throughput: {
    tasksPerSec: number;
    windowSeconds: number;
  };
  oldest_pending_age_sec: number | null;
  oldest_claimed_age_sec: number | null;
}

/** A row from the append-only `events` table, as streamed over SSE. */
export interface EventRow {
  id: number;
  ts: Date;
  type: string;
  job_id: string | null;
  task_id: string | null;
  worker_id: string | null;
  payload: unknown;
}
