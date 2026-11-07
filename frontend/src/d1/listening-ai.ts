/**
 * One-to-one listening AI client and small controller-facing types.
 *
 * Material projection is server-derived from saved fields.  This module only
 * sends the target/action and request identity; it never uploads names, paths
 * or image bytes for an AI task.
 */
import { apiGet, apiPost, pathSegment } from './client'
import { newRequestId, type ListeningDomain } from './listening'

const ROOT = '/api/listening'

export type ListeningAITaskType =
  | 'listening_note_draft'
  | 'listening_domain_evaluate'

export type ListeningAITaskStatus =
  | 'pending'
  | 'claimed'
  | 'dispatching'
  | 'retry_wait'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'outcome_unknown'
  | 'cancelled'

export interface ListeningAITask {
  task_id: string
  task_type: ListeningAITaskType
  status: ListeningAITaskStatus
  reason?: string | null
  source_kind: 'one_to_one_listening'
  listening_record_id: string
  listening_domain: ListeningDomain
  listening_group_id: string | null
  processing_certainty?: string
  user_stop_requested?: boolean
  input_summary?: Record<string, unknown>
  execution?: {
    id: string
    attempt_no: number | null
  } | null
  candidate_id?: string | null
  allowed_actions?: string[]
  retry_requires_ack?: boolean
  created_at?: string
  updated_at?: string
}

export interface ListeningAICandidateEnvelope {
  task: ListeningAITask
  candidate_id: string
  candidate: Record<string, unknown>
  candidate_hash: string
  input_id: string
}

export interface ListeningAIAdoptionPreview {
  preview_token: string
  expires_at: string
  record_id: string
  domain: ListeningDomain
  group_id: string | null
  task_type: ListeningAITaskType
  candidate_id: string
  candidate_hash: string
  targets: string[]
  target_states: Record<string, 'eligible' | 'changed' | 'adopted'>
  proposed: Record<string, unknown>
  revision: number
}

export interface ListeningAIAdoptionResult {
  request_id: string
  operation_kind: 'listening_ai_adopt'
  listening_record_id: string
  domain: ListeningDomain
  group_id: string | null
  revision_after: number
  adopted: Array<Record<string, unknown>>
  replayed: boolean
}

export interface ListeningAICreateReceipt {
  request_id: string
  operation_kind: string
  listening_record_id: string
  domain: ListeningDomain
  group_id: string | null
  task_type: ListeningAITaskType
  task_id: string
  replayed: boolean
}

export function createListeningAITask(input: {
  recordId: string
  domain: ListeningDomain
  groupId: string | null
  taskType: ListeningAITaskType
  expectedRevision: number
  requestId?: string
}): Promise<ListeningAICreateReceipt> {
  return apiPost<ListeningAICreateReceipt>(
    `${ROOT}/records/${pathSegment(input.recordId)}/ai/tasks`,
    {
      request_id: input.requestId ?? newRequestId(),
      expected_revision: input.expectedRevision,
      domain: input.domain,
      group_id: input.groupId,
      task_type: input.taskType,
    },
  )
}

export function getListeningAIOperation(
  recordId: string,
  requestId: string,
): Promise<{
  request_id: string
  operation_kind: string
  status: string
  result: ListeningAICreateReceipt
  created_at: string
}> {
  return apiGet(
    `${ROOT}/records/${pathSegment(recordId)}/ai/operations/${pathSegment(requestId)}`,
  )
}

export function listListeningAITasks(
  recordId: string,
  domain: ListeningDomain,
): Promise<{ items: ListeningAITask[]; next_cursor: string | null }> {
  return apiGet(
    `${ROOT}/records/${pathSegment(recordId)}/ai/tasks?domain=${encodeURIComponent(domain)}&limit=20`,
  )
}

export function getListeningAITask(
  recordId: string,
  taskId: string,
): Promise<ListeningAITask> {
  return apiGet(
    `${ROOT}/records/${pathSegment(recordId)}/ai/tasks/${pathSegment(taskId)}`,
  )
}

export function getListeningAICandidate(
  recordId: string,
  taskId: string,
): Promise<ListeningAICandidateEnvelope> {
  return apiGet(
    `${ROOT}/records/${pathSegment(recordId)}/ai/tasks/${pathSegment(taskId)}/candidate`,
  )
}

export function previewListeningAICandidate(
  recordId: string,
  candidateId: string,
): Promise<ListeningAIAdoptionPreview> {
  return apiPost(
    `${ROOT}/records/${pathSegment(recordId)}/ai/candidates/${pathSegment(candidateId)}/preview-adoption`,
    { candidate_id: candidateId },
  )
}

export function adoptListeningAICandidate(input: {
  recordId: string
  candidateId: string
  requestId: string
  expectedRevision: number
  previewToken: string
  selections: Array<Record<string, unknown>>
}): Promise<ListeningAIAdoptionResult> {
  return apiPost(
    `${ROOT}/records/${pathSegment(input.recordId)}/ai/candidates/${pathSegment(input.candidateId)}/adopt`,
    {
      request_id: input.requestId,
      expected_revision: input.expectedRevision,
      preview_token: input.previewToken,
      selections: input.selections,
    },
  )
}

export function taskIsLive(task: ListeningAITask): boolean {
  return (
    task.status === 'pending' ||
    task.status === 'claimed' ||
    task.status === 'dispatching' ||
    task.status === 'retry_wait'
  )
}

export function taskIsTerminal(task: ListeningAITask): boolean {
  return (
    task.status === 'succeeded' ||
    task.status === 'failed' ||
    task.status === 'outcome_unknown' ||
    task.status === 'cancelled'
  )
}
