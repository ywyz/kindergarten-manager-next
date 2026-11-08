/**
 * One-to-one listening AI client and small controller-facing types.
 *
 * Material projection is server-derived from saved fields.  This module only
 * sends the target/action and request identity; it never uploads names, paths
 * or image bytes for an AI task.
 */
import { ApiError, apiGet, apiPost, pathSegment } from './client'
import { newRequestId, type ListeningDomain } from './listening'

const ROOT = '/api/listening'

export type ListeningAITaskType =
  | 'listening_note_draft'
  | 'listening_domain_evaluate'
  | 'listening_group_notes'
  | 'listening_goal_suggest'

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

export interface ListeningGroupNoteCandidate {
  position: number
  text: string
  uncertainties: string[]
}

export interface ListeningGroupNoteProposal {
  target: string
  position: number
  text: string
  uncertainties: string[]
  current: string
}

/**
 * Client-side shape check for the multi-photo candidate. The server remains
 * authoritative; this only prevents an unsent/duplicate position from being
 * rendered as if it belonged to this request.
 */
export function readListeningGroupNotesCandidate(
  candidate: Record<string, unknown>,
  expectedPositions: number[],
): ListeningGroupNoteCandidate[] {
  if (candidate.mode !== 'group_notes') {
    throw new Error('多图位候选模式不合法')
  }
  const rawGroups = candidate.groups
  if (!Array.isArray(rawGroups) || rawGroups.length < 1 || rawGroups.length > 3) {
    throw new Error('多图位候选数量不合法')
  }
  const groups: ListeningGroupNoteCandidate[] = rawGroups.map((value) => {
    if (!value || typeof value !== 'object') {
      throw new Error('多图位候选结构不合法')
    }
    const item = value as Record<string, unknown>
    const position = item.position
    const text = item.text
    const uncertainties = item.uncertainties
    if (
      !Number.isInteger(position) ||
      (position as number) < 0 ||
      (position as number) > 2 ||
      typeof text !== 'string' ||
      !Array.isArray(uncertainties) ||
      uncertainties.some((entry) => typeof entry !== 'string')
    ) {
      throw new Error('多图位候选结构不合法')
    }
    return {
      position: position as number,
      text,
      uncertainties: uncertainties as string[],
    }
  })
  const positions = groups.map((group) => group.position)
  if (
    positions.length !== new Set(positions).size ||
    positions.join(',') !== expectedPositions.join(',')
  ) {
    throw new Error('多图位候选与已发送图位不一致')
  }
  return groups
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

export const LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN =
  'LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN'

export class ListeningAIAdoptionResponseError extends Error {
  constructor(
    message = '采用响应结构或身份不一致，结果不确定',
  ) {
    super(message)
    this.name = 'ListeningAIAdoptionResponseError'
  }
}

/**
 * A disconnected/unreadable response or the dedicated commit-uncertain 503
 * means the server may already have committed the adoption.  A 2xx whose body
 * is missing required business fields is the same dangerous case: the write
 * may exist, so the original request must remain receipt-recoverable.
 */
export function listeningAIAdoptionIsUncertain(exc: unknown): boolean {
  return (
    exc instanceof ListeningAIAdoptionResponseError ||
    (exc instanceof ApiError &&
      (exc.status === 0 ||
        exc.code === LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN))
  )
}

export interface ListeningAIAdoptionExpectation {
  recordId: string
  domain: ListeningDomain
  requestId: string
  expectedRevision: number
  taskType: ListeningAITaskType
  groupId: string | null
  selections: Array<Record<string, unknown>>
  groups: Array<{ group_id: string; position: number | null }>
}

export interface ListeningAIAdoptionGroupUpdate {
  target: string
  position: number
  group_id: string
  value: string
}

export interface ListeningAIAdoptionResult {
  request_id: string
  operation_kind: 'listening_ai_adopt'
  listening_record_id: string
  domain: ListeningDomain
  group_id: string | null
  revision_after: number
  adopted: Array<Record<string, unknown>>
  group_updates?: ListeningAIAdoptionGroupUpdate[]
  replayed: boolean
}

/**
 * Validate the server's group-note preview.  Candidate identity and target
 * hashes stay server-side; this client check keeps an unsent position, a
 * cross-domain target or a partial group list from being rendered as if it
 * belonged to this domain's displayed candidate.
 */
export function readListeningGroupNotesPreview(
  preview: ListeningAIAdoptionPreview,
): ListeningGroupNoteProposal[] {
  if (preview.task_type !== 'listening_group_notes') {
    throw new Error('预览任务类型不是多图位整理')
  }
  const rawGroups = preview.proposed.groups
  if (!Array.isArray(rawGroups) || rawGroups.length < 1 || rawGroups.length > 3) {
    throw new Error('多图位预览数量不合法')
  }
  const groups: ListeningGroupNoteProposal[] = rawGroups.map((value) => {
    if (!value || typeof value !== 'object') {
      throw new Error('多图位预览结构不合法')
    }
    const item = value as Record<string, unknown>
    const target = item.target
    const position = item.position
    const text = item.text
    const uncertainties = item.uncertainties
    const current = item.current
    if (
      typeof target !== 'string' ||
      !Number.isInteger(position) ||
      (position as number) < 0 ||
      (position as number) > 2 ||
      typeof text !== 'string' ||
      !Array.isArray(uncertainties) ||
      uncertainties.some((entry) => typeof entry !== 'string') ||
      typeof current !== 'string'
    ) {
      throw new Error('多图位预览结构不合法')
    }
    return {
      target,
      position: position as number,
      text,
      uncertainties: uncertainties as string[],
      current,
    }
  })
  const targets = groups.map((group) => group.target)
  const positions = groups.map((group) => group.position)
  if (
    new Set(targets).size !== targets.length ||
    new Set(positions).size !== positions.length
  ) {
    throw new Error('多图位预览图位或目标重复')
  }
  for (const group of groups) {
    if (group.target !== `${preview.domain}_${group.position}`) {
      throw new Error('多图位预览目标与图位不一致')
    }
    if (!(group.target in preview.target_states)) {
      throw new Error('多图位预览目标状态缺失')
    }
  }
  if (
    preview.targets.length !== targets.length ||
    preview.targets.some((target) => !targets.includes(target))
  ) {
    throw new Error('多图位预览目标列表不一致')
  }
  if (
    positions.some(
      (position, index) => index > 0 && position <= positions[index - 1],
    )
  ) {
    throw new Error('多图位预览图位顺序不合法')
  }
  if (targets.some((target, index) => preview.targets[index] !== target)) {
    throw new Error('多图位预览目标顺序不一致')
  }
  return groups
}

/**
 * Convert one adoption receipt into the editor patch.  Group-note positions
 * carry their own group id from the server so the teacher's current field
 * order cannot silently move text to another photo.
 */
export function listeningAIAdoptionPatch(
  result: ListeningAIAdoptionResult,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  const groupUpdates = new Map(
    (result.group_updates ?? []).map((update) => [update.target, update]),
  )
  const evaluation: Record<string, number | null> = {}
  const groupEntries: Array<{
    position: number
    group_id: string
    listening_text: unknown
  }> = []
  for (const item of result.adopted) {
    const target = String(item.target)
    if (target === 'goal') {
      patch.goal = item.value
    } else if (target === 'listening_text') {
      patch.groups = [
        {
          group_id: result.group_id,
          listening_text: item.value,
        },
      ]
    } else if (target === 'overall_evaluation') {
      patch.overall_evaluation = item.value
    } else if (target === 'support_strategy') {
      patch.support_strategy = item.value
    } else if ('value' in item) {
      const update = groupUpdates.get(target)
      const groupId =
        update?.group_id ??
        (typeof item.group_id === 'string' ? item.group_id : '')
      if (!groupId) throw new Error('采用回执缺少图位组标识')
      const position =
        update?.position ??
        (typeof item.position === 'number' ? item.position : -1)
      groupEntries.push({
        position,
        group_id: groupId,
        listening_text: update?.value ?? item.value,
      })
      groupUpdates.delete(target)
    } else {
      evaluation[target] = (item.stars as number | null | undefined) ?? null
    }
  }
  if (groupUpdates.size) {
    throw new Error('采用回执图位与所选目标不一致')
  }
  if (groupEntries.length) {
    if (
      new Set(groupEntries.map((entry) => entry.group_id)).size !==
      groupEntries.length
    ) {
      throw new Error('采用回执图位重复')
    }
    patch.groups = groupEntries
      .sort((left, right) => left.position - right.position)
      .map((entry) => ({
        group_id: entry.group_id,
        listening_text: entry.listening_text,
      }))
  }
  if (Object.keys(evaluation).length) patch.evaluation = evaluation
  return patch
}

function _record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function _fail(message: string): never {
  throw new ListeningAIAdoptionResponseError(message)
}

function _integer(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= minimum &&
    value <= maximum
  )
}

function _exactKeys(
  value: Record<string, unknown>,
  expected: string[],
  message: string,
): void {
  const actual = Object.keys(value)
  if (
    actual.length !== expected.length ||
    actual.some((key) => !expected.includes(key))
  ) {
    _fail(message)
  }
}

/**
 * Validate the complete adoption business response before it can touch the
 * editor.  A 2xx JSON object with missing fields, a different record/domain/
 * request, a revision outside this transaction, or adopted items that do not
 * exactly match the frozen selections is treated as an uncertain result.
 */
export function readListeningAIAdoptionResult(
  value: unknown,
  expected: ListeningAIAdoptionExpectation,
): ListeningAIAdoptionResult {
  if (!_record(value)) _fail('采用响应不是业务对象')
  if (
    typeof expected.requestId !== 'string' ||
    !expected.requestId ||
    typeof expected.recordId !== 'string' ||
    !expected.recordId ||
    !_integer(expected.expectedRevision, 1, Number.MAX_SAFE_INTEGER)
  ) {
    _fail('采用请求身份不完整')
  }
  if (expected.taskType === 'listening_note_draft') {
    if (typeof expected.groupId !== 'string' || !expected.groupId) {
      _fail('采用请求小组身份缺失')
    }
  } else if (expected.groupId !== null) {
    _fail('采用请求小组身份不合法')
  }
  if (value.request_id !== expected.requestId) {
    _fail('采用响应请求 ID 不一致')
  }
  if (value.operation_kind !== 'listening_ai_adopt') {
    _fail('采用响应操作类型不一致')
  }
  if (value.listening_record_id !== expected.recordId) {
    _fail('采用响应记录身份不一致')
  }
  if (value.domain !== expected.domain) {
    _fail('采用响应领域身份不一致')
  }
  if (value.group_id !== expected.groupId) {
    _fail('采用响应小组身份不一致')
  }
  if (typeof value.replayed !== 'boolean') {
    _fail('采用响应重放标记不合法')
  }
  const revision = value.revision_after
  if (
    !_integer(revision, 1, Number.MAX_SAFE_INTEGER) ||
    (revision !== expected.expectedRevision &&
      revision !== expected.expectedRevision + 1)
  ) {
    _fail('采用响应修订不合理')
  }

  const selectedByTarget = new Map<string, Record<string, unknown>>()
  for (const selection of expected.selections) {
    if (!_record(selection)) _fail('采用请求选项不合法')
    const target = selection.target
    if (
      typeof target !== 'string' ||
      !target ||
      selectedByTarget.has(target)
    ) {
      _fail('采用请求目标重复或不合法')
    }
    const hasValue = Object.prototype.hasOwnProperty.call(selection, 'value')
    const hasStars = Object.prototype.hasOwnProperty.call(selection, 'stars')
    if (hasValue === hasStars) {
      _fail('采用请求选项内容不合法')
    }
    selectedByTarget.set(target, selection)
  }
  if (!selectedByTarget.size) _fail('采用请求没有目标')

  const rawAdopted = value.adopted
  if (
    !Array.isArray(rawAdopted) ||
    rawAdopted.length === 0 ||
    rawAdopted.length !== selectedByTarget.size
  ) {
    _fail('采用响应采用项数量不合法')
  }
  const adoptedByTarget = new Map<string, Record<string, unknown>>()
  const groupAdopted: Array<{
    target: string
    position: number
    group_id: string
    value: string
  }> = []
  for (const raw of rawAdopted) {
    if (!_record(raw)) _fail('采用响应采用项结构不合法')
    const target = raw.target
    if (
      typeof target !== 'string' ||
      !target ||
      adoptedByTarget.has(target)
    ) {
      _fail('采用响应目标重复或不合法')
    }
    const selection = selectedByTarget.get(target)
    if (!selection) _fail('采用响应包含未选择的采用项')
    if (Object.prototype.hasOwnProperty.call(selection, 'value')) {
      if (typeof selection.value !== 'string') {
        _fail('采用请求文本不合法')
      }
      if (expected.taskType === 'listening_group_notes') {
        _exactKeys(
          raw,
          ['target', 'position', 'group_id', 'value'],
          '采用响应图位字段不合法',
        )
        const position = raw.position
        const groupId = raw.group_id
        const text = raw.value
        if (!_integer(position, 0, 2)) {
          _fail('采用响应图位不合法')
        }
        if (typeof groupId !== 'string' || !groupId) {
          _fail('采用响应图位小组缺失')
        }
        // The saved server value is authoritative.  Do not re-implement
        // Python strip() with JS trim(): their Unicode sets differ.
        if (typeof text !== 'string') {
          _fail('采用响应图位正文不合法')
        }
        if (target !== `${expected.domain}_${position}`) {
          _fail('采用响应图位目标不一致')
        }
        const current = expected.groups.find(
          (group) => group.position === position,
        )
        if (!current || current.group_id !== groupId) {
          _fail('采用响应图位小组不一致')
        }
        groupAdopted.push({
          target,
          position,
          group_id: groupId,
          value: text,
        })
      } else {
        _exactKeys(
          raw,
          ['target', 'value'],
          '采用响应文本字段不合法',
        )
        // Accept the server-normalized saved text as-is; only its type and
        // selected target identity are client-checked.
        if (typeof raw.value !== 'string') {
          _fail('采用响应文本不合法')
        }
        if (expected.taskType === 'listening_note_draft') {
          if (target !== 'listening_text') {
            _fail('采用响应单图目标不一致')
          }
        } else if (expected.taskType === 'listening_goal_suggest') {
          if (target !== 'goal') {
            _fail('采用响应观察目标不一致')
          }
        } else if (
          target !== 'overall_evaluation' &&
          target !== 'support_strategy'
        ) {
          _fail('采用响应领域文本目标不一致')
        }
      }
    } else {
      if (expected.taskType === 'listening_group_notes') {
        _fail('采用响应图位内容不合法')
      }
      _exactKeys(raw, ['target', 'stars'], '采用响应星级字段不合法')
      const selectedStars = selection.stars
      if (
        selectedStars !== null &&
        selectedStars !== 1 &&
        selectedStars !== 2 &&
        selectedStars !== 3
      ) {
        _fail('采用请求星级不合法')
      }
      const stars = raw.stars
      if (
        stars !== null &&
        stars !== 1 &&
        stars !== 2 &&
        stars !== 3
      ) {
        _fail('采用响应星级不合法')
      }
      if (stars !== selectedStars) {
        _fail('采用响应星级不一致')
      }
      if (
        target === 'overall_evaluation' ||
        target === 'support_strategy' ||
        target === 'listening_text' ||
        !target.startsWith(`${expected.domain}_`)
      ) {
        _fail('采用响应领域评价目标不一致')
      }
    }
    adoptedByTarget.set(target, raw)
  }
  if (adoptedByTarget.size !== selectedByTarget.size) {
    _fail('采用响应缺少采用项')
  }

  const rawGroupUpdates = value.group_updates
  if (expected.taskType === 'listening_group_notes') {
    if (
      !Array.isArray(rawGroupUpdates) ||
      rawGroupUpdates.length === 0 ||
      rawGroupUpdates.length !== groupAdopted.length
    ) {
      _fail('采用响应图位更新数量不合法')
    }
    const updatedTargets = new Set<string>()
    for (const raw of rawGroupUpdates) {
      if (!_record(raw)) _fail('采用响应图位更新结构不合法')
      _exactKeys(
        raw,
        ['target', 'position', 'group_id', 'value'],
        '采用响应图位更新字段不合法',
      )
      const target = raw.target
      const position = raw.position
      const groupId = raw.group_id
      const text = raw.value
      if (
        typeof target !== 'string' ||
        !target ||
        updatedTargets.has(target) ||
        !_integer(position, 0, 2) ||
        typeof groupId !== 'string' ||
        !groupId ||
        typeof text !== 'string'
      ) {
        _fail('采用响应图位更新不合法')
      }
      const adopted = groupAdopted.find((item) => item.target === target)
      if (
        !adopted ||
        adopted.position !== position ||
        adopted.group_id !== groupId ||
        adopted.value !== text
      ) {
        _fail('采用响应图位更新不一致')
      }
      updatedTargets.add(target)
    }
    if (updatedTargets.size !== groupAdopted.length) {
      _fail('采用响应图位更新缺少目标')
    }
  } else if (rawGroupUpdates !== undefined) {
    if (!Array.isArray(rawGroupUpdates) || rawGroupUpdates.length > 0) {
      _fail('采用响应包含多余图位更新')
    }
  }

  return {
    request_id: expected.requestId,
    operation_kind: 'listening_ai_adopt',
    listening_record_id: expected.recordId,
    domain: expected.domain,
    group_id: expected.groupId,
    revision_after: revision,
    adopted: rawAdopted as Array<Record<string, unknown>>,
    ...(expected.taskType === 'listening_group_notes'
      ? {
          group_updates:
            rawGroupUpdates as ListeningAIAdoptionGroupUpdate[],
        }
      : {}),
    replayed: value.replayed === true,
  }
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
}): Promise<unknown> {
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
