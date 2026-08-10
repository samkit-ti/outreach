/**
 * Postgres access. Pool size 10 (LLD §8: `2W + API pool (10)`).
 *
 * All transactions run at READ COMMITTED (Postgres default) — deliberate, per LLD §3:
 * every guard in the system is a conditional write, so nothing relies on snapshot
 * stability and there are no serialization retries to handle.
 */
import pg from 'pg';
import { config } from './config.js';

const { Pool } = pg;

/**
 * BIGSERIAL and BIGINT come back as strings by default (js number can't hold int8).
 * events.id fits comfortably in a double at our volumes and is used as an SSE cursor,
 * so parse it as a number. Type OID 20 = int8.
 */
pg.types.setTypeParser(20, (v: string) => Number(v));

export const pool: pg.Pool = new Pool({
  connectionString: config.databaseUrl,
  max: config.pgPoolSize,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 10_000,
});

pool.on('error', (err: Error) => {
  // An idle client erroring out is not fatal — the pool replaces it.
  console.error(JSON.stringify({ level: 'error', msg: 'pg idle client error', err: err.message }));
});

export type Queryable = Pick<pg.PoolClient, 'query'>;

/** Run `fn` inside a single transaction; rollback on any throw. */
export async function withTransaction<T>(fn: (client: pg.PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const out = await fn(client);
    await client.query('COMMIT');
    return out;
  } catch (err) {
    try {
      await client.query('ROLLBACK');
    } catch {
      // Connection is likely dead; releasing it with an error discards it from the pool.
    }
    throw err;
  } finally {
    client.release();
  }
}

/** Wait for Postgres to accept connections — compose brings us up alongside it. */
export async function waitForDatabase(attempts = 60, delayMs = 1000): Promise<void> {
  for (let i = 1; i <= attempts; i += 1) {
    try {
      await pool.query('SELECT 1');
      return;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.log(
        JSON.stringify({ level: 'warn', msg: 'waiting for postgres', attempt: i, err: message }),
      );
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw new Error(`postgres not reachable after ${attempts} attempts`);
}

export async function closePool(): Promise<void> {
  await pool.end();
}
