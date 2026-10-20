/**
 * D2 W5 operation receipts (engineering spec §5.1/§5.2, product §9.3 #8).
 *
 * Every D2 AI write carries a globally unique ``request_id``. When a response
 * is lost the page must **only read** the committed receipt for that exact
 * key; an unknown receipt is not a failure and the key/body are never swapped.
 * The receipt endpoint is read-only and never replays a provider request.
 */

import { apiGet, ApiError } from './client'
import type { AiOperationReceipt } from './types'

export type ReceiptQuery =
  | { state: 'found'; result: Record<string, unknown> }
  /** 404 AI_OPERATION_NOT_FOUND: nothing committed under this key (not a failure). */
  | { state: 'unknown' }
  /** Transport / other error: the outcome cannot be told and must stay pending. */
  | { state: 'unavailable' }

export async function queryAiReceipt(requestId: string): Promise<ReceiptQuery> {
  try {
    const receipt = await apiGet<AiOperationReceipt>(
      `/api/local/ai/operations/${encodeURIComponent(requestId)}`,
    )
    return { state: 'found', result: receipt.result }
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return { state: 'unknown' }
    return { state: 'unavailable' }
  }
}

/** Stable human text for a receipt query state. */
export function receiptMessage(query: ReceiptQuery): string {
  switch (query.state) {
    case 'found':
      return '已通过提交回执确认结果'
    case 'unknown':
      return '提交结果未知：不会自动换键，请稍后再次查询'
    default:
      return '查询暂不可用：结果仍待核对，请稍后重试'
  }
}

/**
 * Whether a write failure is *indeterminate* (the operation may have been
 * applied). Status 0 covers a transport failure **and** an unreadable 2xx body
 * (``client.ts`` reports it as status 0); a 5xx is also treated conservatively
 * because a server error does not prove the write did not commit. Callers keep
 * their complete original request and reconcile through the receipt — never a
 * new key. A definite 4xx (validation/conflict) is NOT indeterminate.
 *
 * The one exception is an explicitly documented **pre-commit** refusal: the
 * server returns it from an availability check *before* writing anything
 * (engineering §4.1/§5.4), so a first attempt can be shown as a definite
 * failure instead of a pending unknown. Resubmitting an *already pending* key
 * still must NOT clear that pending from such a refusal alone (the original
 * request may still be committing concurrently) — that is handled by the
 * caller.
 */
const DEFINITE_SERVER_REFUSAL_CODES = new Set(['AI_EXECUTOR_UNAVAILABLE'])

export function isIndeterminate(err: unknown): boolean {
  const status = (err as { status?: unknown })?.status
  if (typeof status !== 'number') return false
  if (status === 0) return true
  if (
    err instanceof ApiError &&
    typeof err.code === 'string' &&
    DEFINITE_SERVER_REFUSAL_CODES.has(err.code)
  ) {
    return false
  }
  return status >= 500
}
