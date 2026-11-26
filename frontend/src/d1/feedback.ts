/**
 * Typed client for the in-app online feedback entry.
 *
 * The panel only talks to the same-origin local API; the teacher-typed
 * content, the optional contact and the receipt live in panel memory (never
 * in browser storage or a URL).  The application version is filled in by the
 * local backend, not by this module.  Since 2026-11-24 no feedback code is
 * sent (the field exists upstream only for already-released clients), and a
 * submission may attach the recent local diagnostics events — the same
 * bounded, fixed-shape window this client reads from the local API.
 */

import { apiGet, apiPost } from './client'

export interface FeedbackStatus {
  configured: boolean
  app_version: string
  message: string | null
}

/** One fixed-shape diagnostic event (strict: four fixed fields only). */
export interface FeedbackDiagnosticsEvent {
  event_type: 'export_word' | 'local_backup' | 'webdav_backup' | 'webdav_download' | 'webdav_restore' | 'local_restore' | 'update_check' | 'update_download' | 'save_daily_plan' | 'save_weekly_plan' | 'save_observation' | 'save_listening' | 'save_curriculum'
  time: string
  result: 'ok' | 'canceled' | 'failed' | 'unknown'
  error_code: string | null
}

/** The bounded recent window the panel may attach (newest first). */
export interface FeedbackDiagnosticsSnapshot {
  events: FeedbackDiagnosticsEvent[]
}

export interface FeedbackSubmissionInput {
  request_id: string
  content: string
  contact: string | null
  /** Attached only when the teacher kept the attach choice on a non-empty window. */
  diagnostics?: FeedbackDiagnosticsEvent[]
}

export interface FeedbackReceipt {
  submission_id: string
  request_id: string
  received_at: string
  replayed: boolean
}

export function getFeedbackStatus(): Promise<FeedbackStatus> {
  return apiGet<FeedbackStatus>('/api/local/feedback/status')
}

export function getFeedbackDiagnosticsEvents(): Promise<FeedbackDiagnosticsSnapshot> {
  return apiGet<FeedbackDiagnosticsSnapshot>('/api/local/feedback/diagnostics-events')
}

export function submitFeedback(
  input: FeedbackSubmissionInput,
): Promise<FeedbackReceipt> {
  return apiPost<FeedbackReceipt>('/api/local/feedback/submissions', input)
}
