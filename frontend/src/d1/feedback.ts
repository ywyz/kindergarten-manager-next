/**
 * Typed client for the in-app online feedback entry.
 *
 * The panel only talks to the same-origin local API; the feedback code, the
 * teacher-typed content and the receipt live in panel memory (never in
 * browser storage or a URL).  The application version is filled in by the
 * local backend, not by this module.
 */

import { apiGet, apiPost } from './client'

export interface FeedbackStatus {
  configured: boolean
  app_version: string
  message: string | null
}

export interface FeedbackSubmissionInput {
  request_id: string
  feedback_code: string
  content: string
  contact: string | null
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

export function submitFeedback(
  input: FeedbackSubmissionInput,
): Promise<FeedbackReceipt> {
  return apiPost<FeedbackReceipt>('/api/local/feedback/submissions', input)
}
