/**
 * D1 typed API client: same-origin fetch with the per-launch app session
 * header (module memory only — never in the URL, storage or logs), typed
 * error envelope ({error:{code,message,details?}}), and a request helper
 * that keeps `details` for callers (config version conflicts, export acks).
 */

export const SESSION_HEADER = 'X-App-Session'

let sessionToken: string | null = null

export function setSessionToken(token: string | null): void {
  sessionToken = token
}

export function hasSessionToken(): boolean {
  return sessionToken !== null
}

/** Session header for the raw-binary export request (token stays in memory). */
export function sessionHeaders(): Record<string, string> {
  return sessionToken !== null ? { [SESSION_HEADER]: sessionToken } : {}
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
}

export class ApiError extends Error {
  status: number
  code?: string
  details?: Record<string, unknown>

  constructor(
    status: number,
    message: string,
    code?: string,
    details?: Record<string, unknown>,
  ) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

/** Sentinel for a body that could not be read/parsed (never returned). */
const UNREADABLE = Symbol('unreadable')

function toError(status: number, body: unknown): ApiError {
  const error = (body as ApiErrorBody)?.error
  const code = error?.code
  const message = error?.message || `请求失败（HTTP ${status}）`
  return new ApiError(status, message, code, error?.details)
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { 'cache-control': 'no-store' }
  if (sessionToken !== null) headers[SESSION_HEADER] = sessionToken
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers:
        body === undefined
          ? headers
          : { ...headers, 'content-type': 'application/json' },
      mode: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (err) {
    // Transport-level failure: no HTTP status (may or may not have reached
    // the server — callers must treat saves as indeterminate).
    throw new ApiError(0, `网络请求异常：${String(err)}`)
  }
  const payload = await response.json().catch(() => UNREADABLE)
  if (!response.ok) {
    throw toError(response.status, payload === UNREADABLE ? null : payload)
  }
  if (payload === UNREADABLE || payload === null) {
    // A 2xx whose body could not be read/parsed (truncated / invalid JSON) is
    // NOT a successful empty result: the server may already have applied the
    // operation. Report an indeterminate outcome (status 0) so callers keep
    // their original request and reconcile through the receipt, instead of
    // returning null and polluting business state.
    throw new ApiError(
      0,
      `响应无法解析：结果未知（HTTP ${response.status}）`,
    )
  }
  return payload as T
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>('GET', path)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body ?? {})
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>('PATCH', path, body)
}

/** Percent-encode one path segment (term/plan/request ids are opaque). */
export function pathSegment(value: string): string {
  return encodeURIComponent(value)
}
