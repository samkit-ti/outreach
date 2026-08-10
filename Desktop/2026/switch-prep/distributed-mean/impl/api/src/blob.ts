/**
 * Minimal S3 client — presign + inline proxy only. **The API never writes to the object
 * store** (DM-005: the API is off the data plane; workers own every byte). There is no
 * PutObject call anywhere in this service, by construction.
 *
 * `GET /jobs/:id/result` 302s to a 15-minute pre-signed GET so the result bytes go
 * client↔S3 directly. `?inline=1` proxies the stream instead — an explicit opt-in for
 * curl/demo ergonomics on a small C, never the path a real consumer takes.
 */
import type { Readable } from 'node:stream';
import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { config } from './config.js';

export const s3: S3Client = new S3Client({
  endpoint: config.s3Endpoint,
  region: config.s3Region,
  forcePathStyle: config.s3ForcePathStyle,
  credentials: {
    accessKeyId: config.s3AccessKey,
    secretAccessKey: config.s3SecretKey,
  },
});

/** LLD §7: our bucket layout. The result is `jobs/{jobId}/result.csv`. */
export function resultKey(jobId: string): string {
  return `jobs/${jobId}/result.csv`;
}

export function resultUri(jobId: string): string {
  return `s3://${config.s3Bucket}/${resultKey(jobId)}`;
}

/**
 * Split an `s3://bucket/key` URI. Used to honour a job's stored `result_uri` when the
 * worker wrote somewhere other than the default template.
 */
export function parseS3Uri(uri: string): { bucket: string; key: string } | null {
  try {
    const u = new URL(uri);
    if (u.protocol !== 's3:') return null;
    const key = u.pathname.replace(/^\//, '');
    if (u.hostname === '' || key === '') return null;
    return { bucket: u.hostname, key: decodeURIComponent(key) };
  } catch {
    return null;
  }
}

/** A 15-minute pre-signed GET (DM-005). */
export async function presignResultUrl(bucket: string, key: string): Promise<string> {
  return getSignedUrl(s3, new GetObjectCommand({ Bucket: bucket, Key: key }), {
    expiresIn: config.presignExpirySeconds,
  });
}

export interface InlineObject {
  body: Readable;
  contentType: string;
  contentLength: number | undefined;
}

/** The `?inline=1` proxy path. Streams; nothing is buffered in the Node process. */
export async function getObjectStream(bucket: string, key: string): Promise<InlineObject> {
  const out = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  if (out.Body === undefined) {
    throw new Error(`object ${bucket}/${key} returned no body`);
  }
  return {
    body: out.Body as Readable,
    contentType: out.ContentType ?? 'text/csv',
    contentLength: out.ContentLength,
  };
}

export function isNoSuchKey(err: unknown): boolean {
  if (typeof err !== 'object' || err === null) return false;
  const e = err as { name?: string; Code?: string; $metadata?: { httpStatusCode?: number } };
  return e.name === 'NoSuchKey' || e.Code === 'NoSuchKey' || e.$metadata?.httpStatusCode === 404;
}
