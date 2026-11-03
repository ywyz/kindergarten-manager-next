/**
 * Weekly editor core: whitelist PATCH diff, stable identity/version split,
 * manual-ID reconciliation, unknown receipt recovery and Q3 export chains.
 *
 * Pure state/DTO logic only; no Vue, DOM, fetch, host or native save.
 */
import type { BlockingDraft, SaveOutcome } from './leave'
import {
  canonicalWeeklyJson,
  newWeeklyRequestId,
  cloneWeekly,
  normalizeWeeklyTheme,
  projectWeeklyError,
  type WeeklyApi,
  type WeeklyConfirmationPreview,
  type WeeklyConfirmationSummary,
  type WeeklyDailySelector,
  type WeeklyDraft,
  type WeeklyDraftContent,
  type WeeklyExportOperation,
  type WeeklyExportPreview,
  type WeeklyRefreshPreview,
  type WeeklyFact,
  type WeeklyFocusChoice,
  type WeeklyGameChoice,
  type WeeklyGamePatch,
  type WeeklyPatch,
  type WeeklyWriteResult,
  type WeeklyDetail,
} from './weekly'

export type WeeklyEditorStatus =
  | 'idle'
  | 'saving'
  | 'refreshing'
  | 'confirming'
  | 'exporting'
  | 'unknown'
  | 'conflict'

export interface WeeklyEditorSnapshot {
  identity: string
  loaded_draft_version: number
  dirty: boolean
  input_revision: number
  sequence: number
  busy: boolean
  blocking: boolean
  status: WeeklyEditorStatus
}

export interface WeeklyEditorOptions {
  detail: WeeklyDetail
  api: WeeklyApi
  editorEpoch?: number
  settle?: () => Promise<void>
  requestId?: () => string
}

export interface WeeklyWriteTicket {
  request_id: string
  identity: string
  expected_version: number
  input_revision: number
  sequence: number
  action: 'save' | 'refresh' | 'confirm'
  submitted: WeeklyDraftContent
  patch?: WeeklyPatch
  preview_token?: string
  context_token?: string
  ack_missing?: boolean
  ack_stale?: boolean
  note?: string | null
}

export interface WeeklyWriteOutcome {
  result: 'saved' | 'conflict' | 'failed' | 'indeterminate' | 'unchanged'
  write?: WeeklyWriteResult
  message?: string
}


function sameValue(left: unknown, right: unknown): boolean {
  return canonicalWeeklyJson(left) === canonicalWeeklyJson(right)
}

function selectorFromGame(game: WeeklyGameChoice): WeeklyGamePatch {
  if (game.source_kind === 'daily_plan') {
    return {
      source_kind: 'daily_plan',
      daily_plan_id: game.daily_plan_id,
      content_id: game.content_id,
      content_version: game.content_version,
      content_hash: game.content_hash,
      section: game.section,
      group_id: game.group_id,
      game_id: game.game_id,
    }
  }
  if (game.source_kind === 'ai_supplement') throw new Error('AI 补充项必须保留原值或整体替换')
  return {
    source_kind: 'manual',
    manual_item_id: game.manual_item_id ?? null,
    client_key: game.manual_item_id ? null : game.client_key ?? null,
    name: game.name,
    shared_objectives: game.shared_objectives,
    guidance_points: game.guidance_points,
    focus_guidance: game.focus_guidance,
  }
}

function selectorFromFocus(focus: WeeklyFocusChoice): WeeklyDailySelector {
  if (focus.source_kind === 'ai_supplement') throw new Error('AI 补充重点必须保留原值或整体替换')
  return {
    source_kind: 'daily_plan',
    daily_plan_id: focus.daily_plan_id,
    content_id: focus.content_id,
    content_version: focus.content_version,
    content_hash: focus.content_hash,
    section: focus.section,
    group_id: focus.group_id,
    game_id: focus.game_id,
  }
}

/** Build only whitelist changes; unchanged source/effective/facts are omitted. */
export function weeklyPatchFrom(
  baseline: WeeklyDraftContent,
  current: WeeklyDraftContent,
): WeeklyPatch {
  const patch: WeeklyPatch = {}
  const theme = normalizeWeeklyTheme(current.theme)
  if (theme !== normalizeWeeklyTheme(baseline.theme)) patch.theme = theme

  const byDate = new Map(baseline.deterministic.map((day) => [day.date, day]))
  const overrides: NonNullable<WeeklyPatch['deterministic_overrides']> = {}
  for (const day of current.deterministic) {
    const old = byDate.get(day.date)
    if (old && !sameValue(old.override, day.override)) {
      overrides[day.date] = {
        morning_talk_topic: day.override.morning_talk_topic,
        group_activity_theme: day.override.group_activity_theme,
      }
    }
  }
  if (Object.keys(overrides).length) patch.deterministic_overrides = overrides

  const slots: NonNullable<WeeklyPatch['outdoor_game_slots']> = {}
  for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as const) {
    const before = baseline.outdoor_game_slots[key]
    const after = current.outdoor_game_slots[key]
    if (!sameValue(before, after)) {
      slots[key] = after === null ? null : selectorFromGame(after)
    }
  }
  if (Object.keys(slots).length) patch.outdoor_game_slots = slots

  if (!sameValue(baseline.focus_area, current.focus_area)) {
    patch.focus_area = current.focus_area === null ? null : selectorFromFocus(current.focus_area)
  }

  const columns: Partial<WeeklyDraftContent['weekly_columns']> = {}
  for (const key of [
    'key_week_focus',
    'environment_setup',
    'habit_culture',
    'home_cooperation',
  ] as const) {
    const after = current.weekly_columns[key]
    if (after !== baseline.weekly_columns[key]) columns[key] = after
  }
  if (current.materials !== baseline.materials) patch.materials = current.materials
  if (Object.keys(columns).length) patch.weekly_columns = columns
  return patch
}

export function weeklyPatchIsEmpty(patch: WeeklyPatch): boolean {
  return Object.keys(patch).length === 0
}

function applyLaterInput(response: WeeklyDraftContent, submitted: WeeklyDraftContent, later: WeeklyDraftContent): WeeklyDraftContent {
  const next = cloneWeekly(response)
  if (!sameValue(submitted.theme, later.theme)) next.theme = later.theme
  for (const oldDay of submitted.deterministic) {
    const day = later.deterministic.find((item) => item.date === oldDay.date)
    if (day && !sameValue(oldDay.override, day.override)) {
      const target = next.deterministic.find((item) => item.date === oldDay.date)
      if (target) target.override = cloneWeekly(day.override)
    }
  }
  for (const key of ['key_week_focus', 'environment_setup', 'habit_culture', 'home_cooperation'] as const) {
    if (submitted.weekly_columns[key] !== later.weekly_columns[key]) next.weekly_columns[key] = later.weekly_columns[key]
  }
  for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as const) {
    if (!sameValue(submitted.outdoor_game_slots[key], later.outdoor_game_slots[key])) next.outdoor_game_slots[key] = cloneWeekly(later.outdoor_game_slots[key])
  }
  if (!sameValue(submitted.focus_area, later.focus_area)) next.focus_area = cloneWeekly(later.focus_area)
  if (submitted.materials !== later.materials) next.materials = later.materials
  return next
}

export interface ManualMergeResult {
  content: WeeklyDraftContent
  applied: number
  conflicts: string[]
}

/** Merge server manual IDs only into the same still-live client-key item. */
export function mergeManualIds(
  current: WeeklyDraftContent,
  submitted: WeeklyDraftContent,
  response: WeeklyDraftContent,
): ManualMergeResult {
  const merged = cloneWeekly(current)
  let applied = 0
  const conflicts: string[] = []
  for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as const) {
    const sent = submitted.outdoor_game_slots[key]
    if (!sent || sent.source_kind !== 'manual' || !sent.client_key) continue
    const received = response.outdoor_game_slots[key]
    const live = merged.outdoor_game_slots[key]
    if (!live || live.source_kind !== 'manual' || live.client_key !== sent.client_key) {
      continue
    }
    if (!received || received.source_kind !== 'manual' || !received.manual_item_id) {
      conflicts.push(`outdoor_game_slots.${key}.manual_item_id`)
      continue
    }
    if (live.manual_item_id && live.manual_item_id !== received.manual_item_id) {
      conflicts.push(`outdoor_game_slots.${key}.manual_item_id`)
      continue
    }
    live.manual_item_id = received.manual_item_id
    applied += 1
  }
  return { content: merged, applied, conflicts }
}

export class WeeklyEditorController {
  private detail: WeeklyDetail
  private form: WeeklyDraftContent
  private baseline: WeeklyDraftContent
  private loadedVersion: number
  private editorEpoch: number
  private inputRevision = 0
  private sequence = 0
  private status: WeeklyEditorStatus = 'idle'
  private busyReasons = new Set<string>()
  private savePromise: Promise<SaveOutcome> | null = null
  private flightCounter = 0
  private refreshToken = 0
  private confirmToken = 0
  private retryPromise: Promise<WeeklyWriteResult | null> | null = null
  private lastTicket: WeeklyWriteTicket | null = null
  private lastOperation: WeeklyWriteResult | null = null
  private unknown = false
  private acceptedDraft: { id: string; version: number; content_hash: string } | null = null
  private factsPending = false
  private factsMismatch = false
  private factsGeneration = 0

  private selectedConfirmation: WeeklyConfirmationSummary | null = null
  private readonly listeners = new Set<() => void>()
  private readonly api: WeeklyApi
  private readonly settleHook?: () => Promise<void>
  private readonly makeRequestId: () => string

  constructor(options: WeeklyEditorOptions) {
    this.detail = options.detail
    this.form = cloneWeekly(options.detail.draft.content)
    this.baseline = cloneWeekly(options.detail.draft.content)
    this.loadedVersion = options.detail.draft.version
    this.editorEpoch = options.editorEpoch ?? 0
    this.api = options.api
    this.settleHook = options.settle
    this.makeRequestId = options.requestId ?? newWeeklyRequestId
    this.selectedConfirmation = options.detail.confirmed
  }

  hasUnknown(): boolean { return this.unknown }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private notify(): void {
    for (const listener of this.listeners) {
      try { listener() } catch { /* UI-only listener */ }
    }
  }

  getContent(): WeeklyDraftContent { return cloneWeekly(this.form) }
  getDetail(): WeeklyDetail { return this.detail }
  isFactsPending(): boolean { return this.factsPending }
  factsAreStale(): boolean { return this.factsMismatch }

  getLoadedDraftVersion(): number { return this.loadedVersion }
  getLastOperation(): WeeklyWriteResult | null { return this.lastOperation }
  getSelectedConfirmation(): WeeklyConfirmationSummary | null { return this.selectedConfirmation }

  setSelectedConfirmation(confirmation: WeeklyConfirmationSummary | null): void {
    this.selectedConfirmation = confirmation
  }

  replaceContent(next: WeeklyDraftContent): void {
    this.form = cloneWeekly(next)
    this.inputRevision += 1
    if (this.status === 'conflict' || this.status === 'unknown') this.status = 'idle'
    this.notify()
  }

  updateContent(mutator: (draft: WeeklyDraftContent) => void): void {
    const next = cloneWeekly(this.form)
    mutator(next)
    this.replaceContent(next)
  }

  identity(): string { return `${this.detail.plan.id}:${this.editorEpoch}` }
  isDirty(): boolean { return !weeklyPatchIsEmpty(weeklyPatchFrom(this.baseline, this.form)) }
  isBusy(): boolean { return this.busyReasons.size > 0 || this.unknown }

  blockingDraft(): BlockingDraft | null {
    if (!this.isBusy()) return null
    return {
      kind: 'weekly',
      message: this.unknown
        ? '周计划提交结果未确认，请先核对原请求后再离开'
        : '周计划保存、确认或导出仍在进行，请等待结果后再离开',
    }
  }

  snapshot(): WeeklyEditorSnapshot {
    return {
      identity: this.identity(),
      loaded_draft_version: this.loadedVersion,
      dirty: this.isDirty(),
      input_revision: this.inputRevision,
      sequence: this.sequence,
      busy: this.isBusy(),
      blocking: this.blockingDraft() !== null,
      status: this.status,
    }
  }

  async settle(): Promise<void> { await this.settleHook?.() }

  private beginBusy(reason: string): void { this.busyReasons.add(reason); this.notify() }
  private endBusy(reason: string): void { this.busyReasons.delete(reason); this.notify() }

  private applyConfirmation(confirmation: WeeklyConfirmationSummary): void {
    this.selectedConfirmation = confirmation
    this.detail = {
      ...this.detail,
      plan: { ...this.detail.plan, current_confirmed_version: confirmation.version },
      confirmed: confirmation,
    }
  }

  private async reconcileFacts(generation: number): Promise<void> {
    const accepted = this.acceptedDraft
    if (!accepted) return
    const identity = this.identity()
    try {
      const fetched = await this.api.get(this.detail.plan.id)
      if (generation !== this.factsGeneration || this.identity() !== identity) return
      if (fetched.draft.id === accepted.id && fetched.draft.version === accepted.version && fetched.draft.content_hash === accepted.content_hash) {
        this.detail = {
          ...this.detail,
          facts: cloneWeekly(fetched.facts),
          source_candidates: cloneWeekly(fetched.source_candidates),
          source_context_hash: fetched.source_context_hash,
          plan: { ...this.detail.plan, header: fetched.plan.header, current_draft_version: fetched.plan.current_draft_version, current_confirmed_version: fetched.plan.current_confirmed_version },
        }
        this.factsPending = false
        this.factsMismatch = false
      } else {
        this.factsPending = true
        this.factsMismatch = true
      }
      this.notify()
    } catch {
      if (generation === this.factsGeneration) { this.factsPending = true; this.notify() }
    }
  }
  private applySaved(result: WeeklyWriteResult, ticket: WeeklyWriteTicket): boolean {
    if (!result.draft) return false
    const response = cloneWeekly(result.draft.content)
    this.baseline = cloneWeekly(response)
    this.loadedVersion = result.draft.version
    this.acceptedDraft = { id: result.draft.id, version: result.draft.version, content_hash: result.draft.content_hash }
    this.factsGeneration += 1
    this.factsPending = true
    this.factsMismatch = false
    const factsGeneration = this.factsGeneration
    void this.reconcileFacts(factsGeneration)

    this.detail = {
      ...this.detail,
      plan: {
        ...this.detail.plan,
        current_draft_version: result.draft.version,
        current_confirmed_version: result.confirmation?.version ?? this.detail.plan.current_confirmed_version,
      },
      draft: result.draft,
      confirmed: result.confirmation ?? this.detail.confirmed,
    }
    this.lastOperation = result
    this.unknown = false
    if (this.identity() === ticket.identity && this.inputRevision === ticket.input_revision) {
      this.form = cloneWeekly(response)
    } else if (ticket.action === 'refresh') {
      const overlay = applyLaterInput(response, ticket.submitted, this.form)
      const merged = mergeManualIds(overlay, ticket.submitted, response)
      this.form = merged.content
      if (merged.conflicts.length) {
        this.status = 'conflict'
        return false
      }
    } else {
      const merged = mergeManualIds(this.form, ticket.submitted, response)
      this.form = merged.content
      if (merged.conflicts.length) {
        this.status = 'conflict'
        return false
      }
    }
    this.status = 'idle'
    return true
  }

  saveCurrent(): Promise<SaveOutcome> {
    if (this.savePromise) return this.savePromise
    if (this.unknown) return Promise.resolve('indeterminate')
    const entryIdentity = this.identity()
    const flightId = ++this.flightCounter
    const busyReason = `saving:${flightId}`
    this.beginBusy(busyReason)
    this.status = 'saving'
    const work = (async (): Promise<SaveOutcome> => {
      try {
        try { await this.settle() } catch { if (this.identity() === entryIdentity) this.status = 'idle'; return 'failed' }
        if (this.identity() !== entryIdentity) return 'failed'
        const patch = weeklyPatchFrom(this.baseline, this.form)
        if (weeklyPatchIsEmpty(patch)) { this.status = 'idle'; return 'unchanged' }
        const ticket: WeeklyWriteTicket = {
          request_id: this.makeRequestId(), identity: entryIdentity,
          expected_version: this.loadedVersion, input_revision: this.inputRevision,
          sequence: this.sequence + 1, action: 'save', submitted: cloneWeekly(this.form), patch,
        }
        this.sequence = ticket.sequence
        this.lastTicket = ticket
        try {
          const result = await this.api.save(this.detail.plan.id, {
            request_id: ticket.request_id, expected_draft_version: ticket.expected_version, patch,
          })
          if (this.identity() !== ticket.identity) return 'failed'
          if (!this.applySaved(result, ticket)) return 'conflict'
          return 'saved'
        } catch (error) {
          if (this.identity() !== ticket.identity) return 'failed'
          const projected = projectWeeklyError(error)
          if (projected.code === 'WEEKLY_UNKNOWN') { this.unknown = true; this.status = 'unknown'; return 'indeterminate' }
          if (projected.code === 'WEEKLY_VERSION_CONFLICT' || projected.retry === 'reload') { this.status = 'conflict'; return 'conflict' }
          this.status = 'idle'
          return 'failed'
        }
      } finally {
        this.endBusy(busyReason)
      }
    })()
    this.savePromise = work
    void work.finally(() => { if (this.savePromise === work) this.savePromise = null }).catch(() => {})
    return work
  }
  resetForContext(reason: 'restore' | 'profile-replace' | 'retire', editorEpoch: number): void {
    this.editorEpoch = editorEpoch
    this.inputRevision += 1
    this.sequence += 1
    this.savePromise = null
    this.lastTicket = null
    this.lastOperation = null
    this.unknown = false
    this.busyReasons.clear()
    this.confirmToken = 0
    this.retryPromise = null
    this.refreshToken = 0
    this.status = 'idle'
    this.selectedConfirmation = null
    this.acceptedDraft = null
    this.factsPending = false
    this.factsMismatch = false
    this.factsGeneration += 1
    this.notify()
  }

async refreshSources(preview: WeeklyRefreshPreview): Promise<WeeklyWriteOutcome> {
    if (this.unknown) throw new Error('周计划提交结果未确认，请先核对原请求')
    if (this.refreshToken) return { result: 'failed', message: '刷新正在进行' }
    const currentVersion = this.loadedVersion
    if (preview.target_draft_version !== currentVersion + 1) return { result: 'conflict', message: '刷新预览已过期，请重新预览' }
    const refreshId = ++this.flightCounter
    const refreshReason = `refreshing:${refreshId}`
    this.refreshToken = refreshId
    const identity = this.identity()
    const ticket: WeeklyWriteTicket = {
      request_id: this.makeRequestId(),
      identity,
      expected_version: currentVersion,
      input_revision: this.inputRevision,
      sequence: this.sequence + 1,
      action: 'refresh',
      submitted: cloneWeekly(this.form),
      preview_token: preview.preview_token,
    }
    this.sequence = ticket.sequence
    this.lastTicket = ticket
    this.beginBusy(refreshReason)
    this.status = 'refreshing'

    try {
      await this.settle()
      if (this.identity() !== identity) return { result: 'failed' }
      const result = await this.api.refreshSources(this.detail.plan.id, {
        request_id: ticket.request_id,
        expected_draft_version: ticket.expected_version,
        preview_token: ticket.preview_token!,
      })
      if (this.identity() !== identity) return { result: 'failed' }
      if (!this.applySaved(result, ticket)) return { result: 'conflict' }
      return { result: 'saved', write: result }
    } catch (error) {
      if (this.identity() !== identity) return { result: 'failed' }
      const projected = projectWeeklyError(error)
      if (projected.code === 'WEEKLY_UNKNOWN') {
        this.unknown = true
        this.status = 'unknown'
        return { result: 'indeterminate', message: projected.message }
      }
      if (projected.code === 'WEEKLY_VERSION_CONFLICT' || projected.code === 'WEEKLY_PREVIEW_STALE') {
        this.status = 'conflict'
        return { result: 'conflict', message: projected.message }
      }
      this.status = 'idle'
      return { result: 'failed', message: projected.message }
    } finally {
      if (this.refreshToken === refreshId) this.refreshToken = 0
      this.endBusy(refreshReason)
    }
  }
  async queryOperation(requestId?: string): Promise<WeeklyWriteResult | null> {
    const id = requestId ?? this.lastTicket?.request_id
    if (!id) return null
    const entryIdentity = this.identity()
    const queryReason = `query:${++this.flightCounter}`
    this.beginBusy(queryReason)
    try {
      const result = await this.api.getBusinessOperation(id)
      if (this.identity() !== entryIdentity) return null
      this.lastOperation = result
      this.unknown = false
      this.status = 'idle'
      const ticket = this.lastTicket
      if (
        ticket &&
        ticket.request_id === id &&
        result.request_id === ticket.request_id &&
        this.identity() === ticket.identity
      ) {
        if (
          (ticket.action === 'save' || ticket.action === 'refresh') &&
          result.draft &&
          this.loadedVersion <= ticket.expected_version
        ) {
          this.applySaved(result, ticket)
        } else if (ticket.action === 'confirm' && result.confirmation) {
          if (result.confirmation) this.applyConfirmation(result.confirmation)
        }
      }
      return result
    } catch (error) {
      if (this.identity() !== entryIdentity) return null
      const projected = projectWeeklyError(error)
      if (projected.code === 'WEEKLY_OPERATION_NOT_FOUND') {
        this.unknown = true
        this.status = 'unknown'
      } else {
        this.status = 'conflict'
      }
      return null
    } finally {
      this.endBusy(queryReason)
    }
  }

  async retryOriginalOperation(): Promise<WeeklyWriteResult | null> {
    if (!this.unknown || !this.lastTicket) return null
    const ticket = this.lastTicket
    if (this.identity() !== ticket.identity) return null
    if (this.retryPromise) return this.retryPromise
    const retryReason = `retry-original:${++this.flightCounter}`
    this.beginBusy(retryReason)
    this.status = 'unknown'
    const work = (async (): Promise<WeeklyWriteResult | null> => {
      try {
        if (ticket.action === 'save') {
          const result = await this.api.save(this.detail.plan.id, {
            request_id: ticket.request_id,
            expected_draft_version: ticket.expected_version,
            patch: cloneWeekly(ticket.patch ?? {}),
          })
          if (this.identity() !== ticket.identity) return null
          this.lastOperation = result
          this.unknown = false
          this.status = 'idle'
          if (result.draft && this.loadedVersion <= ticket.expected_version) {
            this.applySaved(result, ticket)
          }
          return result
        }
        if (ticket.action === 'refresh' && ticket.preview_token) {
          const result = await this.api.refreshSources(this.detail.plan.id, {
            request_id: ticket.request_id,
            expected_draft_version: ticket.expected_version,
            preview_token: ticket.preview_token,
          })
          if (this.identity() !== ticket.identity) return null
          this.lastOperation = result
          this.unknown = false
          this.status = 'idle'
          if (result.draft && this.loadedVersion <= ticket.expected_version) this.applySaved(result, ticket)
          return result
        }
        if (ticket.action === 'confirm' && ticket.context_token) {
          const result = await this.api.confirm(this.detail.plan.id, {
            request_id: ticket.request_id,
            expected_draft_version: ticket.expected_version,
            context_token: ticket.context_token,
            ack_missing: ticket.ack_missing ?? false,
            ack_stale: ticket.ack_stale ?? false,
            note: ticket.note ?? null,
          })
          if (this.identity() !== ticket.identity) return null
          this.lastOperation = result
          if (result.confirmation) this.applyConfirmation(result.confirmation)
          this.unknown = false
          this.status = 'idle'
          return result
        }
        return null
      } catch (error) {
        if (this.identity() !== ticket.identity) return null
        const projected = projectWeeklyError(error)
        if (projected.code === 'WEEKLY_UNKNOWN') {
          this.unknown = true
          this.status = 'unknown'
        } else {
          this.status = 'conflict'
        }
        return null
      } finally {
        this.endBusy(retryReason)
      }
    })()
    this.retryPromise = work
    try {
      return await work
    } finally {
      if (this.retryPromise === work) this.retryPromise = null
    }
  }
  async refreshPreview(): Promise<WeeklyRefreshPreview> {
    if (this.unknown) throw new Error('周计划提交结果未确认，请先核对原请求')
    const previewReason = `refresh-preview:${++this.flightCounter}`
    this.beginBusy(previewReason)
    this.status = 'refreshing'
    const identity = this.identity()
    const revision = this.inputRevision
    try {
      const preview = await this.api.refreshPreview(this.detail.plan.id, this.loadedVersion)
      if (this.identity() !== identity || this.inputRevision !== revision) {
        throw new Error('周计划内容已变化，请重新预览')
      }
      this.sequence += 1
      return preview
    } finally {
      this.endBusy(previewReason)
      if (this.status === 'refreshing') this.status = 'idle'
    }
  }

  async confirmationPreview(): Promise<WeeklyConfirmationPreview> {
    const confirmationReason = `confirmation-preview:${++this.flightCounter}`
    this.beginBusy(confirmationReason)
    const identity = this.identity()
    const revision = this.inputRevision
    try {
      await this.settle()
      if (this.isDirty()) throw new Error('请先保存当前周计划再确认')
      if (this.identity() !== identity || this.inputRevision !== revision) {
        throw new Error('周计划内容已变化，请重新确认')
      }
      const preview = await this.api.confirmationPreview(this.detail.plan.id, this.loadedVersion)
      if (this.identity() !== identity || this.inputRevision !== revision) {
        throw new Error('周计划内容已变化，请重新确认')
      }
      return preview
    } finally {
      this.endBusy(confirmationReason)
      if (this.status === 'confirming') this.status = 'idle'
    }
  }
  async confirm(
    preview: WeeklyConfirmationPreview,

    options: { ack_missing?: boolean; ack_stale?: boolean; note?: string | null } = {},
  ): Promise<WeeklyWriteOutcome> {
    if (this.confirmToken) return { result: 'indeterminate', message: '确认正在处理' }
    const confirmId = ++this.flightCounter
    const confirmReason = `confirming:${confirmId}`
    this.confirmToken = confirmId
    this.beginBusy(confirmReason)
    const identity = this.identity()
    const revision = this.inputRevision
    const ticket: WeeklyWriteTicket = {
      request_id: this.makeRequestId(),
      identity,
      expected_version: preview.target.draft_version,
      input_revision: revision,
      sequence: this.sequence + 1,
      action: 'confirm',
      submitted: cloneWeekly(this.form),
      context_token: preview.preview_token,
      ack_missing: options.ack_missing ?? false,
      ack_stale: options.ack_stale ?? false,
      note: options.note ?? null,
    }
    this.sequence = ticket.sequence
    this.lastTicket = ticket

    this.status = 'confirming'
    try {
      const result = await this.api.confirm(this.detail.plan.id, {
        request_id: ticket.request_id,
        expected_draft_version: preview.target.draft_version,
        context_token: ticket.context_token!,
        ack_missing: ticket.ack_missing!,
        ack_stale: ticket.ack_stale!,
        note: ticket.note ?? null,
      })
      if (this.identity() !== identity) return { result: 'failed' }
      if (!result.confirmation) return { result: 'failed' }
      this.applyConfirmation(result.confirmation)
      this.lastOperation = result
      this.unknown = false
      this.status = 'idle'
      return { result: 'saved', write: result }
    } catch (error) {
      if (this.identity() !== identity) return { result: 'failed' }
      const projected = projectWeeklyError(error)
      if (projected.code === 'WEEKLY_UNKNOWN') {
        this.unknown = true
        this.status = 'unknown'
        return { result: 'indeterminate', message: projected.message }
      }
      if (
        projected.code === 'WEEKLY_VERSION_CONFLICT' ||
        projected.code === 'WEEKLY_PREVIEW_STALE'
      ) {
        this.status = 'conflict'
        return { result: 'conflict', message: projected.message }
      }
      this.status = 'idle'
      return { result: 'failed', message: projected.message }
    } finally {
      if (this.confirmToken === confirmId) this.confirmToken = 0
      this.endBusy(confirmReason)
    }
  }
  savedDraftRef(): { id: string; version: number; content_hash: string } {
    return { id: this.detail.draft.id, version: this.loadedVersion, content_hash: this.detail.draft.content_hash }
  }

  beginExternalBusy(reason: string): () => void {
    this.beginBusy(reason)
    let done = false
    return () => { if (done) return; done = true; this.endBusy(reason) }
  }

  reconcileExternalDraft(detail: WeeklyDetail, guard: { identity: string; input_revision: number; sequence: number }, submitted: WeeklyDraftContent, acceptedDraft: { id: string; version: number; content_hash: string }): 'applied' | 'stale' | 'conflict' {
    if (this.identity() !== guard.identity || this.sequence !== guard.sequence) return 'stale'
    if (detail.draft.id !== acceptedDraft.id || detail.draft.version !== acceptedDraft.version || detail.draft.content_hash !== acceptedDraft.content_hash) return 'conflict'
    const later = this.form
    const laterRevision = this.inputRevision
    let nextForm: WeeklyDraftContent
    if (laterRevision === guard.input_revision) {
      nextForm = cloneWeekly(detail.draft.content)
    } else {
      const overlay = applyLaterInput(detail.draft.content, submitted, later)
      const merged = mergeManualIds(overlay, submitted, detail.draft.content)
      if (merged.conflicts.length) return 'conflict'
      nextForm = merged.content
    }
    this.detail = detail
    this.baseline = cloneWeekly(detail.draft.content)
    this.loadedVersion = detail.draft.version
    this.acceptedDraft = { ...acceptedDraft }
    this.form = nextForm
    this.status = 'idle'
    this.unknown = false
    this.notify()
    return 'applied'
  }
}
export interface WeeklyConfirmDecision {
  ack_missing: boolean
  ack_stale: boolean
  note?: string | null
}

export type WeeklyQ3Result =
  | { status: 'exported'; confirmation: WeeklyConfirmationSummary; exported: WeeklyExportOperation }
  | {
      status: 'stayed'
      reason: 'new_input' | 'identity_changed' | 'not_clean' | 'save_failed' | 'not_confirmed' | 'unknown' | 'cancelled'
    }

export interface WeeklyCurrentExportDeps {
  identity(): string
  inputRevision(): number
  sequence(): number
  isDirty(): boolean
  settle(): Promise<void>
  saveCurrent(): Promise<SaveOutcome>
  loadedDraftVersion(): number
  confirmationPreview(expectedVersion: number): Promise<WeeklyConfirmationPreview>
  decide(preview: WeeklyConfirmationPreview): Promise<WeeklyConfirmDecision | null>
  confirm(
    preview: WeeklyConfirmationPreview,
    decision: WeeklyConfirmDecision,
  ): Promise<WeeklyWriteOutcome>
  exportPreview(confirmation: WeeklyConfirmationSummary): Promise<WeeklyExportPreview>
  exportCreate(preview: WeeklyExportPreview, requestId: string): Promise<WeeklyExportOperation>
  requestId?: () => string
}

function q3Guard(deps: WeeklyCurrentExportDeps, identity: string, revision: number): boolean {
  return deps.identity() === identity && deps.inputRevision() === revision
}


export async function runCurrentWeeklyExport(
  deps: WeeklyCurrentExportDeps,
): Promise<WeeklyQ3Result> {
  await deps.settle()
  const identity = deps.identity()
  const revision = deps.inputRevision()
  const saved = await deps.saveCurrent()
  if (!q3Guard(deps, identity, revision)) return { status: 'stayed', reason: 'identity_changed' }
  if (saved !== 'saved' && saved !== 'unchanged') {
    return { status: 'stayed', reason: saved === 'indeterminate' ? 'unknown' : 'save_failed' }
  }
  if (deps.isDirty()) return { status: 'stayed', reason: 'new_input' }

  const afterSaveSequence = deps.sequence()
  const preview = await deps.confirmationPreview(deps.loadedDraftVersion())
  if (
    !q3Guard(deps, identity, revision) ||
    deps.sequence() !== afterSaveSequence ||
    deps.isDirty()
  ) {
    return { status: 'stayed', reason: 'identity_changed' }
  }
  const decision = await deps.decide(preview)
  if (!q3Guard(deps, identity, revision) || deps.sequence() !== afterSaveSequence) {
    return { status: 'stayed', reason: 'identity_changed' }
  }
  if (decision === null) return { status: 'stayed', reason: 'cancelled' }

  const outcome = await deps.confirm(preview, decision)
  if (!q3Guard(deps, identity, revision)) return { status: 'stayed', reason: 'identity_changed' }
  if (outcome.result === 'indeterminate') return { status: 'stayed', reason: 'unknown' }
  if (outcome.result !== 'saved' || !outcome.write?.confirmation) {
    return { status: 'stayed', reason: 'not_confirmed' }
  }
  const confirmation = outcome.write.confirmation
  if (
    confirmation.draft_version !== preview.target.draft_version ||
    confirmation.snapshot_hash !== preview.target_hash
  ) {
    return { status: 'stayed', reason: 'not_confirmed' }
  }

  const afterConfirmSequence = deps.sequence()
  const exportPreview = await deps.exportPreview(confirmation)
  if (!q3Guard(deps, identity, revision) || deps.sequence() !== afterConfirmSequence) {
    return { status: 'stayed', reason: 'identity_changed' }
  }
  const exported = await deps.exportCreate(
    exportPreview,
    deps.requestId?.() ?? newWeeklyRequestId(),
  )
  if (!q3Guard(deps, identity, revision)) return { status: 'stayed', reason: 'identity_changed' }
  if (exported.generation_status !== 'generated') {
    return { status: 'stayed', reason: 'unknown' }
  }
  return { status: 'exported', confirmation, exported }
}

export interface WeeklyPreviousExportDeps {
  exportPreview(confirmation: WeeklyConfirmationSummary): Promise<WeeklyExportPreview>
  exportCreate(preview: WeeklyExportPreview, requestId: string): Promise<WeeklyExportOperation>
  requestId?: () => string
}

export async function runPreviousWeeklyExport(
  confirmation: WeeklyConfirmationSummary | null,
  deps: WeeklyPreviousExportDeps,
): Promise<WeeklyQ3Result> {
  if (!confirmation) return { status: 'stayed', reason: 'not_confirmed' }
  const preview = await deps.exportPreview(confirmation)
  const exported = await deps.exportCreate(
    preview,
    deps.requestId?.() ?? newWeeklyRequestId(),
  )
  if (exported.generation_status !== 'generated') {
    return { status: 'stayed', reason: 'unknown' }
  }
  return { status: 'exported', confirmation, exported }
}
