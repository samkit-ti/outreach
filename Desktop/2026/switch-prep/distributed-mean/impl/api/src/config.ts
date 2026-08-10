/**
 * Configuration — LLD §8. Every knob is env-driven; defaults match the demo topology
 * in LLD §9 (compose service names postgres/minio/api/worker/supervisor/ui).
 */

function str(name: string, fallback: string): string {
  const v = process.env[name];
  return v === undefined || v === '' ? fallback : v;
}

function int(name: string, fallback: number): number {
  const v = process.env[name];
  if (v === undefined || v === '') return fallback;
  const n = Number(v);
  if (!Number.isFinite(n) || !Number.isInteger(n)) {
    throw new Error(`env ${name} must be an integer, got ${JSON.stringify(v)}`);
  }
  return n;
}

function bool(name: string, fallback: boolean): boolean {
  const v = process.env[name];
  if (v === undefined || v === '') return fallback;
  return v === 'true' || v === '1' || v === 'yes';
}

function csv(name: string, fallback: string): string[] {
  return str(name, fallback)
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export const config = {
  port: int('PORT', 8080),

  databaseUrl: str('DATABASE_URL', 'postgres://dm:dm@postgres:5432/dm'),
  /** LLD §8: "DB pool sizing 2W + API pool (10)" — the API's half is 10. */
  pgPoolSize: int('PG_POOL_SIZE', 10),

  s3Endpoint: str('S3_ENDPOINT', 'http://minio:9000'),
  s3AccessKey: str('S3_ACCESS_KEY', 'minioadmin'),
  s3SecretKey: str('S3_SECRET_KEY', 'minioadmin'),
  s3Bucket: str('S3_BUCKET', 'distributed-mean'),
  s3Region: str('S3_REGION', 'us-east-1'),
  s3ForcePathStyle: bool('S3_FORCE_PATH_STYLE', true),

  /**
   * LLD §8 / HLD §9: buckets/hosts a worker may READ inputs from. Checked here at
   * submit and again at read by the worker's BlobStore — the object behind a URI can
   * change between the two.
   */
  inputUriAllowlist: csv('INPUT_URI_ALLOWLIST', 's3://distributed-mean/'),

  /** LLD §8 admission control. 5 GB demo default. */
  maxJobBytes: int('MAX_JOB_BYTES', 5_368_709_120),
  maxActiveJobs: int('MAX_ACTIVE_JOBS', 8),
  /** Retry-After seconds served with the 429. */
  retryAfterSeconds: int('RETRY_AFTER_SECONDS', 10),

  /** LLD §8: K_FANIN = 5 — the RAM constraint, and T1's chunk size for inputUris[]. */
  kFanin: int('K_FANIN', 5),

  /** LLD §1 bounds, mirrored by zod at the edge (LLD §6). */
  minF: 2,
  maxF: 99_999,
  minC: 2,
  maxC: 999_999,

  /** DM-005: result pre-signed GET lifetime. */
  presignExpirySeconds: int('PRESIGN_EXPIRY_SECONDS', 15 * 60),

  /** DM-009 SSE tuning. */
  sse: {
    /** The 1 Hz coalesced snapshot frame. */
    snapshotIntervalMs: int('SSE_SNAPSHOT_INTERVAL_MS', 1000),
    /** Event tail poll cadence. */
    tailIntervalMs: int('SSE_TAIL_INTERVAL_MS', 500),
    /** Keepalive comment; must stay under the ALB's 60 s idle timeout. */
    keepaliveMs: int('SSE_KEEPALIVE_MS', 15_000),
    /** Rows per tail read. */
    tailBatch: int('SSE_TAIL_BATCH', 200),
  },

  /** DM-009: liveness window for the workers table (30 s lease). */
  workerAliveSeconds: int('WORKER_ALIVE_SECONDS', 30),
  /** DM-008: W_max. PATCH /system/workers accepts 0..32. */
  maxDesiredWorkers: int('MAX_DESIRED_WORKERS', 32),
  /** LLD §8: DESIRED_WORKERS seed. */
  desiredWorkersSeed: int('DESIRED_WORKERS', 4),

  /** GET /jobs pagination. */
  defaultPageLimit: 50,
  maxPageLimit: 200,
} as const;

export type Config = typeof config;
