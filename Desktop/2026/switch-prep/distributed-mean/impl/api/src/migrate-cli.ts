/** Standalone migration entrypoint: `npm run migrate`. The server also runs these on boot. */
import { closePool, waitForDatabase } from './db.js';
import { runMigrations } from './migrate.js';

try {
  await waitForDatabase();
  await runMigrations();
  await closePool();
  process.exit(0);
} catch (err) {
  console.error(
    JSON.stringify({
      level: 'error',
      component: 'migrate-cli',
      msg: 'migration failed',
      err: err instanceof Error ? err.message : String(err),
    }),
  );
  process.exit(1);
}
