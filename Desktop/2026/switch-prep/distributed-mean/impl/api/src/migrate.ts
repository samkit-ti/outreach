/**
 * Migration runner — applied on boot (LLD §9 runbook: "migrations applied by the API on boot").
 *
 * Deliberately minimal: execute the .sql files in `migrations/` in lexicographic order,
 * each in its own transaction, recording the filename in `schema_migrations`. Idempotent:
 * an already-recorded file is skipped, so re-running is a no-op. `001_init.sql` is the
 * LLD §1 DDL verbatim and is the single schema source for the whole system — the Python
 * worker/supervisor side codes against it.
 *
 * Concurrency: several API replicas may boot at once, so the runner takes a session-level
 * advisory lock for the duration. The loser waits, then finds every file already recorded.
 */
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type pg from 'pg';
import { config } from './config.js';
import { pool } from './db.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
/** dist/migrate.js → ../migrations, so the same path resolves in dev (src/) and in the image. */
const MIGRATIONS_DIR = process.env.MIGRATIONS_DIR ?? path.resolve(HERE, '..', 'migrations');

/** Arbitrary but fixed key for the boot-time migration lock. */
const MIGRATION_LOCK_KEY = 815_233_001;

const LEDGER_DDL = `
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename    TEXT PRIMARY KEY,
  checksum    TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);`;

function log(msg: string, extra: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ level: 'info', component: 'migrate', msg, ...extra }));
}

export async function runMigrations(): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query('SELECT pg_advisory_lock($1)', [MIGRATION_LOCK_KEY]);
    try {
      await client.query(LEDGER_DDL);

      const applied = new Map<string, string>();
      const { rows } = await client.query<{ filename: string; checksum: string }>(
        'SELECT filename, checksum FROM schema_migrations',
      );
      for (const r of rows) applied.set(r.filename, r.checksum);

      const entries = await readdir(MIGRATIONS_DIR);
      const files = entries.filter((f) => f.endsWith('.sql')).sort();
      if (files.length === 0) {
        throw new Error(`no .sql migrations found in ${MIGRATIONS_DIR}`);
      }

      for (const filename of files) {
        const sql = await readFile(path.join(MIGRATIONS_DIR, filename), 'utf8');
        const checksum = createHash('sha256').update(sql).digest('hex');
        const prior = applied.get(filename);

        if (prior !== undefined) {
          if (prior !== checksum) {
            throw new Error(
              `migration ${filename} was modified after being applied ` +
                `(recorded ${prior.slice(0, 12)}, found ${checksum.slice(0, 12)}). ` +
                'Add a new migration instead of editing an applied one.',
            );
          }
          continue;
        }

        log('applying migration', { filename });
        // One transaction per file: DDL in Postgres is transactional, so a failure
        // half-way leaves nothing behind and the ledger row is never written.
        await client.query('BEGIN');
        try {
          await client.query(sql);
          await client.query('INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)', [
            filename,
            checksum,
          ]);
          await client.query('COMMIT');
        } catch (err) {
          await client.query('ROLLBACK');
          throw err;
        }
        log('applied migration', { filename });
      }

      await seedSystemConfig(client);
      log('migrations up to date', { count: files.length });
    } finally {
      await client.query('SELECT pg_advisory_unlock($1)', [MIGRATION_LOCK_KEY]);
    }
  } finally {
    client.release();
  }
}

/**
 * LLD §8: `DESIRED_WORKERS` seed 4; the runtime value lives in `system_config`.
 * Insert-if-absent so a restart never stomps an operator's PATCH.
 */
async function seedSystemConfig(client: pg.PoolClient): Promise<void> {
  await client.query(
    `INSERT INTO system_config (key, value) VALUES ('desired_workers', $1::jsonb)
       ON CONFLICT (key) DO NOTHING`,
    [JSON.stringify(config.desiredWorkersSeed)],
  );
}
