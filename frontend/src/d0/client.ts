/**
 * D0 verification client: same-origin fetch with the per-launch app session
 * header. The token stays in module memory only — never in the URL, never
 * in localStorage, never logged.
 */

const SESSION_HEADER = 'X-App-Session'

let sessionToken: string | null = null

export function setSessionToken(token: string | null): void {
  sessionToken = token
}

export function hasSessionToken(): boolean {
  return sessionToken !== null
}

export type ApiErrorBody = {
  error?: { code?: string; message?: string }
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; code?: string; message: string }

function describe(status: number, body: unknown, fallback: string): string {
  const error = (body as ApiErrorBody)?.error
  if (error?.message) return error.message
  if (error?.code) return `${error.code}（HTTP ${status}）`
  return `${fallback}（HTTP ${status}）`
}

export async function apiGet<T>(path: string, withSession = true): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { 'cache-control': 'no-store' }
  if (withSession && sessionToken !== null) headers[SESSION_HEADER] = sessionToken
  try {
    const response = await fetch(path, { method: 'GET', headers, mode: 'same-origin' })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      return { ok: false, status: response.status, code: (body as ApiErrorBody)?.error?.code, message: describe(response.status, body, '请求失败') }
    }
    return { ok: true, data: body as T }
  } catch (err) {
    return { ok: false, status: 0, message: `网络请求异常：${String(err)}` }
  }
}

export async function apiPost<T>(path: string, body: unknown, withSession = true): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    'cache-control': 'no-store',
  }
  if (withSession && sessionToken !== null) headers[SESSION_HEADER] = sessionToken
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers,
      mode: 'same-origin',
      body: JSON.stringify(body ?? {}),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        code: (data as ApiErrorBody)?.error?.code,
        message: describe(response.status, data, '请求失败'),
      }
    }
    return { ok: true, data: data as T }
  } catch (err) {
    return { ok: false, status: 0, message: `网络请求异常：${String(err)}` }
  }
}

/** Error wording for the probe page. */
export function probeErrorMessage(error: ApiResult<unknown>, fallback: string): string {
  if (error.ok) return fallback
  return error.message
}
