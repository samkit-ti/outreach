/**
 * The API surface — LLD §6, one router. The API never computes and never moves
 * result bytes unless asked to proxy (`?inline=1`); it is control plane only.
 */
import { Router, type Request, type Response, type NextFunction } from 'express';
import { config } from './config.js';
import { badRequest, conflict, notFound, ApiError } from './errors.js';
import {
  decodeCursor,
  getJobRow,
  getJobView,
  listJobs,
  submitJob,
} from './repo/jobs.js';
import {
  getSystemStats,
  readEventsAfter,
  setDesiredWorkers,
} from './repo/stats.js';
import {
  listJobsQueryShape,
  parseOr400,
  patchWorkersShape,
  submitJobShape,
  uuidShape,
  validateSubmitRanges,
  validateUris,
} from './validation.js';
import { getObjectStream, isNoSuchKey, parseS3Uri, presignResultUrl } from './blob.js';

/** Individually-streamed event families; task.* folds into the snapshot (DM-009). */
const STREAMED_PREFIXES = ['job.', 'worker.', 'config.'] as const;

const wrap =
  (fn: (req: Request, res: Response) => Promise<void>) =>
  (req: Request, res: Response, next: NextFunction): void => {
    fn(req, res).catch(next);
  };

export function buildRouter(): Router {
  const router = Router();

  router.post(
    '/jobs',
    wrap(async (req, res) => {
      const body = parseOr400(submitJobShape, req.body, 'bad_submit_body');
      const { f, c } = validateSubmitRanges(body);
      validateUris(body.inputUris);
      const idempotencyKey = req.header('Idempotency-Key') ?? null;
      const result = await submitJob({ f, c, inputUris: body.inputUris, idempotencyKey });
      res.status(result.existing ? 200 : 202).json({ jobId: result.jobId });
    }),
  );

  router.get(
    '/jobs',
    wrap(async (req, res) => {
      const query = parseOr400(listJobsQueryShape, req.query, 'bad_list_query');
      const limit = Math.min(query.limit ?? config.defaultPageLimit, config.maxPageLimit);
      const cursor = query.cursor === undefined ? null : decodeCursor(query.cursor);
      if (query.cursor !== undefined && cursor === null) {
        throw badRequest('bad_cursor', 'cursor is not decodable');
      }
      const page = await listJobs(limit, cursor);
      res.json(page);
    }),
  );

  router.get(
    '/jobs/:id',
    wrap(async (req, res) => {
      const id = parseOr400(uuidShape, req.params.id, 'bad_job_id');
      const view = await getJobView(id);
      if (view === null) throw notFound('job_not_found', `no job ${id}`);
      res.json(view);
    }),
  );

  router.get(
    '/jobs/:id/result',
    wrap(async (req, res) => {
      const id = parseOr400(uuidShape, req.params.id, 'bad_job_id');
      const job = await getJobRow(id);
      if (job === null) throw notFound('job_not_found', `no job ${id}`);
      if (job.status !== 'completed' || job.result_uri === null) {
        throw conflict('result_not_ready', `job is ${job.status}`, { status: job.status });
      }
      const target = parseS3Uri(job.result_uri);
      if (target === null) {
        throw badRequest('bad_result_uri', 'stored result URI is unparseable');
      }
      if (req.query.inline !== undefined) {
        // Demo/curl ergonomics (DM-005): proxy the stream.
        try {
          const object = await getObjectStream(target.bucket, target.key);
          res.setHeader('Content-Type', 'text/csv');
          if (object.contentLength !== undefined) {
            res.setHeader('Content-Length', String(object.contentLength));
          }
          object.body.pipe(res);
        } catch (err) {
          if (isNoSuchKey(err)) throw notFound('result_missing', 'result object not found');
          throw err;
        }
        return;
      }
      // The design path: 302 to a 15-minute pre-signed URL — API off the data plane.
      res.redirect(302, await presignResultUrl(target.bucket, target.key));
    }),
  );

  router.get(
    '/system/stats',
    wrap(async (_req, res) => {
      res.json(await getSystemStats());
    }),
  );

  router.patch(
    '/system/workers',
    wrap(async (req, res) => {
      const body = parseOr400(patchWorkersShape, req.body, 'bad_workers_body');
      if (body.desired > config.maxDesiredWorkers) {
        throw badRequest(
          'w_out_of_range',
          `desired must be 0..${config.maxDesiredWorkers} (W_max, DM-008)`,
        );
      }
      await setDesiredWorkers(body.desired);
      res.json({ desired: body.desired });
    }),
  );

  router.get('/events', (req: Request, res: Response) => {
    res.status(200);
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no'); // and no compression on this route
    res.flushHeaders();

    const lastEventId = Number(req.header('Last-Event-ID') ?? req.query.lastEventId ?? 0);
    let cursor = Number.isFinite(lastEventId) && lastEventId > 0 ? lastEventId : 0;
    let closed = false;

    const write = (chunk: string): void => {
      if (!closed) res.write(chunk);
    };

    const tail = setInterval(() => {
      readEventsAfter(cursor)
        .then((rows) => {
          for (const row of rows) {
            cursor = row.id;
            const streamed = STREAMED_PREFIXES.some((p) => row.type.startsWith(p));
            if (!streamed) continue; // task.* folds into the snapshot frame
            write(`id: ${row.id}\nevent: ${row.type}\ndata: ${JSON.stringify(row)}\n\n`);
          }
        })
        .catch(() => {
          /* transient read failure: next tick retries; the cursor is unchanged */
        });
    }, config.sse.tailIntervalMs);

    const snapshot = setInterval(() => {
      getSystemStats()
        .then((stats) => write(`event: snapshot\ndata: ${JSON.stringify(stats)}\n\n`))
        .catch(() => {
          /* skip this frame */
        });
    }, config.sse.snapshotIntervalMs);

    const keepalive = setInterval(() => write(':keepalive\n\n'), config.sse.keepaliveMs);

    req.on('close', () => {
      closed = true;
      clearInterval(tail);
      clearInterval(snapshot);
      clearInterval(keepalive);
      res.end();
    });
  });

  return router;
}

/** {error:{code,message,details}} everywhere — LLD §6. */
export function errorMiddleware(
  err: unknown,
  _req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof ApiError) {
    for (const [name, value] of Object.entries(err.headers)) res.setHeader(name, value);
    res.status(err.status).json(err.toBody());
    return;
  }
  const message = err instanceof Error ? err.message : String(err);
  console.error(JSON.stringify({ level: 'error', msg: 'unhandled', err: message }));
  res.status(500).json({ error: { code: 'internal_error', message: 'internal error' } });
}
