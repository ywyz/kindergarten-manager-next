/**
 * Pure host-bridge readiness helpers for the D0 window.
 *
 * pywebview assigns ``window.pywebview = { api: {}, ... }`` first and only
 * later fills ``api`` with the exposed functions (then fires
 * ``pywebviewready``). Waiting for ``window.pywebview`` to merely exist is
 * therefore racy: a call made in that gap hits an undefined function. These
 * helpers wait for the *actual* function the page needs, with injectable
 * clock/sleep so the delayed-injection window can be regression-tested
 * without a real WebView2 window.
 *
 * This module intentionally has no runtime imports so it can be exercised
 * directly by Node's TypeScript stripping in the regression test.
 */

export interface HostApi {
  get_session?: () => Promise<{ launch_token?: string }>
  save_docx?: (
    payload: unknown,
  ) => Promise<{ status?: string; path?: string; message?: string }>
}

export interface PywebviewGlobal {
  api?: HostApi
}

export interface BridgeWaitOptions {
  timeoutMs?: number
  pollMs?: number
  now?: () => number
  sleep?: (ms: number) => Promise<void>
}

export const BRIDGE_READY_TIMEOUT_MS = 12000
export const BRIDGE_POLL_MS = 100

export function isSessionApiReady(
  host: PywebviewGlobal | null | undefined,
): boolean {
  return typeof host?.api?.get_session === 'function'
}

export function isSaveApiReady(
  host: PywebviewGlobal | null | undefined,
): boolean {
  return typeof host?.api?.save_docx === 'function'
}

export async function waitForSessionApi(
  getHost: () => PywebviewGlobal | null | undefined,
  options: BridgeWaitOptions = {},
): Promise<'ready' | 'timeout'> {
  const timeoutMs = options.timeoutMs ?? BRIDGE_READY_TIMEOUT_MS
  const pollMs = options.pollMs ?? BRIDGE_POLL_MS
  const now = options.now ?? (() => Date.now())
  const sleep =
    options.sleep ??
    ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)))

  if (isSessionApiReady(getHost())) return 'ready'
  const deadline = now() + timeoutMs
  while (now() < deadline) {
    await sleep(pollMs)
    if (isSessionApiReady(getHost())) return 'ready'
  }
  return 'timeout'
}
