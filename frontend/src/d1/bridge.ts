/**
 * D1 host bridge: bootstrap/session collection, page_ready handshake and the
 * close handshake helpers (complete_close + get_close_state fallback).
 *
 * The host API is pywebview's ``window.pywebview.api``; the token from
 * get_bootstrap stays in the client's module memory only. The pure helpers
 * (resolveCloseOutcome, waitForApi) are regression-tested under Node.
 */

import type { AppIdentity, UpdateStatus } from './update'

export const BRIDGE_PROTOCOL = 1

export interface SaveDocxResult {
  status?: string
  code?: string
  message?: string
  filename?: string
  bytes?: number
}

export interface SaveObservationExportResult {
  status?: string
  code?: string
  message?: string
  filename?: string
  bytes?: number
  export_id?: string
  attempt_id?: string
  receipt_pending?: boolean
}

export interface HostApi {
  get_bootstrap?: () => Promise<{
    bridge_protocol?: number
    launch_token?: string
    page_ticket?: string
    update_install?: {
      plan_id: string
      nonce: string
      version: string
      build_id: string
    } | null
  }>
  page_ready?: (payload: {
    bridge_protocol: number
    page_ticket?: string
    update_install?: {
      plan_id: string
      nonce: string
      version: string
      build_id: string
    } | null
  }) => Promise<{
    accepted?: boolean
    host_protocol?: number
    update_install_error?: string
  }>
  complete_close?: (payload: {
    close_request_id: string
    allow: boolean
    /** D2 §4.3: required when the host reports live AI tasks. */
    task_choice?: 'keep_waiting' | 'stop_and_exit'
  }) => Promise<{ accepted?: boolean; state?: string }>
  get_close_state?: (payload: {
    close_request_id: string
  }) => Promise<{ state?: string }>
  save_docx?: (payload: {
    request_id: string
    filename: string
    payload_base64: string
  }) => Promise<SaveDocxResult>
  get_save_result?: (payload: {
    request_id: string
  }) => Promise<SaveDocxResult>
  save_observation_export?: (payload: {
    export_id: string
    filename: string
  }) => Promise<SaveObservationExportResult>
  get_observation_export_result?: (payload: {
    export_id: string
    filename?: string
  }) => Promise<SaveObservationExportResult>
  reconcile_observation_export_result?: (payload: {
    export_id: string
    filename?: string
  }) => Promise<SaveObservationExportResult>
  get_app_identity?: () => Promise<AppIdentity>
  check_for_update?: () => Promise<UpdateStatus>
  start_update_download?: () => Promise<UpdateStatus>
  cancel_update_download?: () => Promise<UpdateStatus>
  install_update?: () => Promise<{
    accepted?: boolean
    state?: string
    reason?: string
    plan_id?: string
    install_available?: boolean
    update_state?: UpdateStatus
  }>
  get_update_state?: () => Promise<UpdateStatus>
  /** Page-side write barrier for close/update (observation create/import/…). */
  set_page_busy?: (payload: {
    busy: boolean
    seq: number
    page_ticket: string
  }) => Promise<{ accepted?: boolean; busy?: boolean; seq?: number }>
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

export function hostGlobal(): PywebviewGlobal | undefined {
  return (window as unknown as { pywebview?: PywebviewGlobal }).pywebview
}

export function isBootstrapApiReady(
  host: PywebviewGlobal | null | undefined,
): boolean {
  return typeof host?.api?.get_bootstrap === 'function'
}

export async function waitForApi(
  available: () => boolean,
  options: BridgeWaitOptions = {},
): Promise<boolean> {
  const timeoutMs = options.timeoutMs ?? BRIDGE_READY_TIMEOUT_MS
  const pollMs = options.pollMs ?? 100
  const now = options.now ?? (() => Date.now())
  const sleep =
    options.sleep ??
    ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)))
  if (available()) return true
  const deadline = now() + timeoutMs
  while (now() < deadline) {
    await sleep(pollMs)
    if (available()) return true
  }
  return false
}

/**
 * Page-side result of a close attempt (spec §11.3).
 * - ``closing``: the host accepted the final closing: keep the close freeze
 *   until the window is really destroyed; timeouts never unlock it.
 * - ``canceled`` / ``unknown``: the host explicitly reported this request
 *   canceled / not known: release the freeze and stay on the page.
 * - ``pending``: the host is still pending: keep the freeze and the request
 *   id, keep waiting (or let the aborted notification resolve it).
 * - ``unconfirmed``: the bridge could not answer (lost reply, failed
 *   queries): never interpreted as an explicit unknown — the freeze and the
 *   request id stay until the host confirms a terminal state.
 */
export type CloseOutcome =
  | 'closing'
  | 'canceled'
  | 'unknown'
  | 'pending'
  | 'unconfirmed'

export function resolveCloseOutcome(
  complete: { accepted?: boolean; state?: string } | null,
  queried: { state?: string } | null = null,
): CloseOutcome {
  // The host state is authoritative: once the final closing is allowed the
  // page keeps its close freeze, whatever the ack echo says.
  if (complete && complete.state === 'closing') return 'closing'
  if (queried && queried.state === 'closing') return 'closing'
  if (queried && queried.state === 'canceled') return 'canceled'
  if (queried && queried.state === 'unknown') return 'unknown'
  if (queried && queried.state === 'pending') return 'pending'
  if (complete && complete.state === 'canceled') return 'canceled'
  if (complete && complete.state === 'unknown') return 'unknown'
  if (complete && complete.state === 'pending') return 'pending'
  return 'unconfirmed'
}

export interface CloseCallHooks {
  completeClose?: (payload: {
    close_request_id: string
    allow: boolean
    task_choice?: 'keep_waiting' | 'stop_and_exit'
  }) => Promise<{ accepted?: boolean; state?: string }>
  queryCloseState?: (payload: {
    close_request_id: string
  }) => Promise<{ state?: string }>
  /** Number of query attempts when the complete_close response is lost. */
  queryAttempts?: number
  delayMs?: number
  sleep?: (ms: number) => Promise<void>
}

export interface CloseConfirmHooks {
  queryCloseState?: (payload: {
    close_request_id: string
  }) => Promise<CloseStateAnswer>
  /** Attempts per confirmation stage (transport failures only). */
  attemptsPerStage?: number
  delayMs?: number
  /** Per-attempt bound: a hung bridge call never blocks the confirmation. */
  timeoutMs?: number
  sleep?: (ms: number) => Promise<void>
}

/**
 * One ``get_close_state`` answer. ``generation`` is the host-side,
 * monotonically increasing request generation bound to the answer: it is
 * present exactly when the queried id is the host's current request, so two
 * answers with the same generation certify that the same host request
 * instance answered both times (R1 §15.3).
 */
export interface CloseStateAnswer {
  state?: string
  generation?: number
}

/** A confirmed host request: the id is current at this generation. */
export interface CloseAuthority {
  generation: number
}

/**
 * Confirm that ``closeRequestId`` is the host's *current* close request
 * (R1, review §14.3/§15.3). The host answers ``pending`` only for its single
 * current request id and ``unknown`` for every other id, so a notification
 * that arrives out of order (a delayed older request) or after its own
 * timeout is detected here instead of being trusted by arrival order.
 *
 * Two consecutive ``pending`` answers are required, and both must carry the
 * same positive host generation. The generation binds the confirmation to
 * the host's authoritative old/new relationship: a lone answer can be stale
 * in transit — produced while this id was still current and delivered after
 * a newer request was already confirmed on the page — and the second answer
 * has exactly the same transit window. The caller therefore compares the
 * returned generation against the highest generation it already accepted,
 * after every await, and rejects anything not strictly newer.
 *
 * Any other explicit state (canceled / unknown / closing), a missing or
 * mismatching generation, or an unanswerable bridge returns ``null``: the
 * caller stays silent rather than acting on an unconfirmed request.
 */
export async function confirmCurrentCloseRequest(
  closeRequestId: string,
  hooks: CloseConfirmHooks = {},
): Promise<CloseAuthority | null> {
  const attempts = hooks.attemptsPerStage ?? 2
  const delayMs = hooks.delayMs ?? 120
  const timeoutMs = hooks.timeoutMs ?? 2000
  const sleep =
    hooks.sleep ??
    ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)))
  const queryOnce = async (): Promise<CloseStateAnswer | null> => {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      let timer: ReturnType<typeof setTimeout> | null = null
      try {
        const answer = await Promise.race([
          hooks.queryCloseState?.({
            close_request_id: closeRequestId,
          }) ?? Promise.resolve(null),
          new Promise<null>((resolve) => {
            timer = setTimeout(() => resolve(null), timeoutMs)
          }),
        ])
        const state = (answer as CloseStateAnswer | null)?.state
        if (typeof state === 'string' && state) {
          return answer as CloseStateAnswer
        }
      } catch {
        // Transport failure: retried below; never treated as an answer.
      } finally {
        if (timer !== null) clearTimeout(timer)
      }
      if (attempt + 1 < attempts) await sleep(delayMs)
    }
    return null
  }
  const first = await queryOnce()
  if (!first || first.state !== 'pending') return null
  const second = await queryOnce()
  if (!second || second.state !== 'pending') return null
  const generation = first.generation
  if (
    typeof generation !== 'number' ||
    !Number.isInteger(generation) ||
    generation <= 0 ||
    second.generation !== generation
  ) {
    // Both answers must carry the same host generation: without it the
    // confirmation cannot be bound to the host's current request instance.
    return null
  }
  return { generation }
}

/**
 * Send complete_close; on a lost response query get_close_state (bounded).
 * A communication failure is reported as ``unconfirmed`` (never treated as
 * an explicit ``unknown``); ``pending`` means the host still holds the
 * request, so the caller keeps the close freeze and the request id.
 */
export async function completeCloseWithFallback(
  closeRequestId: string,
  allow: boolean,
  hooks: CloseCallHooks,
  taskChoice?: 'keep_waiting' | 'stop_and_exit',
): Promise<CloseOutcome> {
  const sleep =
    hooks.sleep ??
    ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)))
  let complete: { accepted?: boolean; state?: string } | null = null
  let lost = false
  try {
    const payload: {
      close_request_id: string
      allow: boolean
      task_choice?: 'keep_waiting' | 'stop_and_exit'
    } = { close_request_id: closeRequestId, allow }
    if (taskChoice) payload.task_choice = taskChoice
    complete = (await hooks.completeClose?.(payload)) ?? null
  } catch {
    lost = true
  }
  if (!lost && complete) {
    const direct = resolveCloseOutcome(complete)
    if (
      direct === 'closing' ||
      direct === 'canceled' ||
      direct === 'unknown'
    ) {
      return direct
    }
    // pending / unconfirmed acks are confirmed through the bounded queries
    // below, which answer for this exact request id.
  }
  const attempts = hooks.queryAttempts ?? 3
  const delayMs = hooks.delayMs ?? 500
  let queried: { state?: string } | null = null
  let lastExplicit: CloseOutcome = 'unconfirmed'
  for (let i = 0; i < attempts; i += 1) {
    try {
      queried = (await hooks.queryCloseState?.({
        close_request_id: closeRequestId,
      })) ?? null
    } catch {
      queried = null
    }
    const resolved = resolveCloseOutcome(null, queried)
    if (resolved === 'closing' || resolved === 'canceled' || resolved === 'unknown') {
      return resolved
    }
    if (resolved === 'pending') lastExplicit = 'pending'
    await sleep(delayMs)
  }
  return lastExplicit
}

// ---------------------------------------------------------------------------
// Host → page callbacks (registered by the app shell)
// ---------------------------------------------------------------------------

export interface CloseCallbacks {
  /** ``generation`` is the host generation bound to this announcement (R1 §15.3) when the host provides it. */
  onRequestClose?: (closeRequestId: string, generation?: number) => void
  onCloseAborted?: (closeRequestId: string, reason: string) => void
}

export function registerPageHandlers(callbacks: CloseCallbacks): void {
  const target = window as unknown as { __kgmHandlers?: CloseCallbacks }
  target.__kgmHandlers = callbacks
}
