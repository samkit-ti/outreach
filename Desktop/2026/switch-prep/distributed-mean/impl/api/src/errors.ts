/**
 * Error taxonomy — LLD §6.
 *
 *   400 malformed
 *   422 out-of-range, or an input URI that is unparseable, duplicated, or outside
 *       INPUT_URI_ALLOWLIST (the `details` field names the offending URI)
 *   409 result-not-ready
 *   413 job too large (F×C×8 > MAX_JOB_BYTES)
 *   429 too many active jobs (with Retry-After)
 *
 * Body shape is always {error:{code,message,details}}.
 */

export type ErrorDetails = Record<string, unknown> | undefined;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorDetails;
  /** Extra response headers, e.g. Retry-After on a 429. */
  readonly headers: Record<string, string>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: ErrorDetails,
    headers: Record<string, string> = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.headers = headers;
  }

  toBody(): { error: { code: string; message: string; details: ErrorDetails } } {
    return { error: { code: this.code, message: this.message, details: this.details } };
  }
}

export const badRequest = (code: string, message: string, details?: ErrorDetails): ApiError =>
  new ApiError(400, code, message, details);

export const unprocessable = (code: string, message: string, details?: ErrorDetails): ApiError =>
  new ApiError(422, code, message, details);

export const notFound = (code: string, message: string, details?: ErrorDetails): ApiError =>
  new ApiError(404, code, message, details);

export const conflict = (code: string, message: string, details?: ErrorDetails): ApiError =>
  new ApiError(409, code, message, details);

export const payloadTooLarge = (code: string, message: string, details?: ErrorDetails): ApiError =>
  new ApiError(413, code, message, details);

export const tooManyRequests = (
  code: string,
  message: string,
  retryAfterSeconds: number,
  details?: ErrorDetails,
): ApiError =>
  new ApiError(429, code, message, details, { 'Retry-After': String(retryAfterSeconds) });

export const internal = (message: string, details?: ErrorDetails): ApiError =>
  new ApiError(500, 'internal_error', message, details);
