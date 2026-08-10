/**
 * zod at the edge, mirroring the DDL CHECKs (LLD §6). The bounds here and the
 * `CHECK (f BETWEEN 2 AND 99999)` / `CHECK (c BETWEEN 2 AND 999999)` in LLD §1 are the
 * same numbers stated twice on purpose: the DB is the backstop, this is the 422.
 */
import { z } from 'zod';
import { config } from './config.js';
import { badRequest, unprocessable } from './errors.js';

/**
 * POST /jobs body. Shape errors are 400; range/semantic errors are 422 — so the schema
 * validates *shape* loosely on the numeric bounds and the T1 pre-checks do the range
 * work, keeping the status codes honest (LLD §6: "400 malformed / 422 out-of-range").
 */
export const submitJobShape = z
  .object({
    inputUris: z.array(z.string()).nonempty('inputUris must be a non-empty array of strings'),
    c: z.number().int('c must be an integer'),
  })
  .strict();

export type SubmitJobBody = z.infer<typeof submitJobShape>;

export const listJobsQueryShape = z
  .object({
    limit: z.coerce.number().int().positive().max(config.maxPageLimit).optional(),
    cursor: z.string().min(1).optional(),
  })
  .strip();

export const patchWorkersShape = z
  .object({
    desired: z.number().int('desired must be an integer'),
  })
  .strict();

export const uuidShape = z.string().uuid();

/** Translate a zod failure into the 400 of the error taxonomy. */
export function parseOr400<T extends z.ZodTypeAny>(
  schema: T,
  input: unknown,
  code: string,
): z.infer<T> {
  const parsed = schema.safeParse(input);
  if (!parsed.success) {
    throw badRequest(code, 'request body or query is malformed', {
      issues: parsed.error.issues.map((i) => ({
        path: i.path.join('.'),
        message: i.message,
      })),
    });
  }
  return parsed.data;
}

/**
 * LLD §6 §T1 range checks, all 422:
 *   2 ≤ F = inputUris.length ≤ 99999
 *   2 ≤ c ≤ 999999
 *   every URI parses and is in INPUT_URI_ALLOWLIST (details names the offending URI)
 *   no duplicate URIs (a repeated URI would double-weight that vector)
 */
export function validateSubmitRanges(body: SubmitJobBody): { f: number; c: number } {
  const f = body.inputUris.length;

  if (f < config.minF || f > config.maxF) {
    throw unprocessable(
      'f_out_of_range',
      `F (inputUris.length) must be between ${config.minF} and ${config.maxF}`,
      { f, min: config.minF, max: config.maxF },
    );
  }

  if (body.c < config.minC || body.c > config.maxC) {
    throw unprocessable('c_out_of_range', `c must be between ${config.minC} and ${config.maxC}`, {
      c: body.c,
      min: config.minC,
      max: config.maxC,
    });
  }

  validateUris(body.inputUris);
  return { f, c: body.c };
}

/**
 * A URI must parse, must be an `s3://` (or http(s), for a MinIO host form) URI, and must
 * be prefixed by an allow-list entry. Re-checked by the worker's BlobStore at read
 * (LLD §5), because the object behind a URI can change between submit and read.
 */
export function validateUris(uris: readonly string[]): void {
  const seen = new Set<string>();

  for (let i = 0; i < uris.length; i += 1) {
    const uri = uris[i]!;

    if (uri.trim() !== uri || uri.length === 0) {
      throw unprocessable('uri_unparseable', 'input URI has leading/trailing whitespace or is empty', {
        index: i,
        uri,
      });
    }

    let parsed: URL;
    try {
      parsed = new URL(uri);
    } catch {
      throw unprocessable('uri_unparseable', 'input URI does not parse as a URI', { index: i, uri });
    }

    if (!['s3:', 'http:', 'https:'].includes(parsed.protocol)) {
      throw unprocessable('uri_unsupported_scheme', 'input URI scheme is not s3/http/https', {
        index: i,
        uri,
        scheme: parsed.protocol.replace(':', ''),
      });
    }

    // s3://bucket/key requires both a bucket and a non-empty key.
    if (parsed.protocol === 's3:' && (parsed.hostname === '' || parsed.pathname.replace(/^\//, '') === '')) {
      throw unprocessable('uri_unparseable', 'input URI must be s3://<bucket>/<key>', {
        index: i,
        uri,
      });
    }

    if (!isAllowListed(uri)) {
      throw unprocessable(
        'uri_not_allowlisted',
        'input URI is outside INPUT_URI_ALLOWLIST',
        { index: i, uri, allowlist: config.inputUriAllowlist },
      );
    }

    if (seen.has(uri)) {
      // A repeated URI would double-weight that vector (LLD §T1).
      throw unprocessable('duplicate_uri', 'inputUris contains a duplicate URI', { index: i, uri });
    }
    seen.add(uri);
  }
}

export function isAllowListed(uri: string): boolean {
  return config.inputUriAllowlist.some((prefix) => uri.startsWith(prefix));
}

/**
 * LLD §6: `413` if F×C×8 > MAX_JOB_BYTES. Computed in floats deliberately — at the max
 * job F×C×8 is 8e11, well inside Number.MAX_SAFE_INTEGER, so no bigint is needed.
 */
export function jobBytes(f: number, c: number): number {
  return f * c * 8;
}
