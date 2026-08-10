/**
 * Entry point: wait for Postgres → apply migrations → seed desired_workers →
 * serve. Stateless by design (HLD §2): everything lives in Postgres/S3, so a
 * restart mid-job affects nothing.
 */
import express from 'express';
import cors from 'cors';
import { config } from './config.js';
import { closePool, waitForDatabase } from './db.js';
import { runMigrations } from './migrate.js';
import { seedDesiredWorkers } from './repo/stats.js';
import { buildRouter, errorMiddleware } from './routes.js';

async function main(): Promise<void> {
  await waitForDatabase();
  await runMigrations();
  await seedDesiredWorkers();

  const app = express();
  app.use(cors()); // the dashboard is served from another origin (LLD §9)
  app.use(express.json({ limit: '25mb' })); // 100k URIs ≈ several MB of JSON
  app.get('/healthz', (_req, res) => {
    res.json({ ok: true });
  });
  app.use(buildRouter());
  app.use(errorMiddleware);

  const server = app.listen(config.port, () => {
    console.log(JSON.stringify({ level: 'info', msg: 'api listening', port: config.port }));
  });

  const shutdown = (): void => {
    console.log(JSON.stringify({ level: 'info', msg: 'shutting down' }));
    server.close(() => {
      closePool()
        .catch(() => undefined)
        .finally(() => process.exit(0));
    });
    // SSE connections hold the server open; hard stop after the grace window.
    setTimeout(() => process.exit(0), 5000).unref();
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

main().catch((err: unknown) => {
  console.error(JSON.stringify({ level: 'fatal', msg: String(err) }));
  process.exit(1);
});
