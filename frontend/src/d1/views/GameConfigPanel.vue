<script setup lang="ts">
/**
 * D2 W5 class game configuration (product Q4/§9.1, engineering §5.2).
 *
 * Repair round (review §6 R08/R09):
 * - ``confirmed`` is always the REAL server revision, never a snapshot of the
 *   live draft (a later unsubmitted guidance must stay dirty);
 * - an apply whose response is indeterminate keeps its COMPLETE original
 *   request/body, blocks preview/cancel/leaving and is resolved only by a
 *   read-only receipt query or an explicit same-key/same-body re-submit;
 * - the first read is guarded (inputs disabled) and a close freeze disables
 *   all inputs/methods.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import { isIndeterminate, queryAiReceipt, receiptMessage } from '../operations'
import type {
  ClassGames,
  ConfigAICandidate,
  ConfigAITask,
  ConfigPreview,
  GameLocation,
} from '../types'

const props = defineProps<{
  frozen?: boolean
  /** A known local ordinary-setting commit, never an arbitrary server version. */
  committedConfigVersion?: { from: number; to: number } | null
}>()

const emit = defineEmits<{
  (e: 'draft-active', active: boolean): void
  (e: 'applied'): void
}>()

interface GameSnapshot {
  locations: GameLocation[]
  game_scope: string
  guidance: string
}

const current = ref<ClassGames | null>(null)
const loaded = ref(false)
const locations = ref<GameLocation[]>([])
const gameScope = ref('')
const guidance = ref('')
/** The real server state (not the live draft). */
const confirmed = ref<GameSnapshot | null>(null)
const preview = ref<ConfigPreview | null>(null)
const previewing = ref(false)
const applying = ref(false)
const errorText = ref('')
const messageText = ref('')
interface PendingApply {
  requestId: string
  body: Record<string, unknown>
  submitted: GameSnapshot
}
const pendingApply = ref<PendingApply | null>(null)
const importText = ref('')
const parseTask = ref<ConfigAITask | null>(null)
const parseCandidate = ref<ConfigAICandidate | null>(null)
const parseRequestId = ref('')
const parseExpectedVersion = ref<number | null>(null)
const parseSubmittedText = ref('')
const parseKnownTaskId = ref('')
const parseError = ref('')
const parseNotice = ref('')
const parseBusy = ref(false)
const parseCandidateBusy = ref(false)
const parseRecoveryBusy = ref(false)
const parseCreateUnknown = ref(false)
const parseAck = ref(false)
const latestCandidateId = ref('')
const lateCandidate = ref<ConfigAICandidate | null>(null)
const retainedTask = ref<ConfigAITask | null>(null)
const latestTaskRecovered = ref(false)
let parseTimer: ReturnType<typeof setTimeout> | null = null
let parseSeq = 0
let candidateLoadSeq = 0
let inputSeq = 0

function snapshot(): GameSnapshot {
  return {
    locations: locations.value.map((location) => ({ ...location })),
    game_scope: gameScope.value,
    guidance: guidance.value,
  }
}

/** Structured blocking target for the settings shell. */
function draftTargets(): string[] {
  return draftActive.value ? ['game-config'] : []
}

const parsePending = computed(
  () =>
    parseBusy.value ||
    (parseTask.value !== null &&
      ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(parseTask.value.status)),
)
const parseOutcomeUnknown = computed(
  () => parseCreateUnknown.value || parseTask.value?.status === 'outcome_unknown',
)
const parseStatusText = computed(() => {
  const status = parseTask.value?.status
  if (!parseTask.value) return ''
  return (
    {
      pending: '等待处理',
      claimed: '已领取',
      dispatching: '正在解析',
      retry_wait: '等待重试',
      paused: '已暂停',
      succeeded: '已生成候选',
      failed: '解析失败',
      outcome_unknown: '结果不明（可能已处理）',
      cancelled: '已取消',
    }[status ?? ''] ?? status ?? ''
  )
})
const parseReasonText = computed(() => {
  const reason = parseTask.value?.reason
  if (!reason) return ''
  return (
    {
      source_changed: '配置或班级已变化，请重新读取后再解析',
      not_configured: '尚未完成可用的 AI 配置',
      prompt_missing: '解析提示词尚未就绪',
      input_too_large: '粘贴内容超过单次请求上限，请缩短后再试',
      credential_unavailable: 'AI 密钥不可用，请重新保存配置',
      prompt_sync_unavailable: '提示词包同步失败，暂不能使用 AI',
      auth_rejected: '供应商拒绝了当前凭据，请检查 AI 设置',
    }[reason] ?? reason
  )
})
const canStartParse = computed(
  () =>
    loaded.value &&
    importText.value.trim() !== '' &&
    !parseBusy.value &&
    !parseCandidateBusy.value &&
    !parseRecoveryBusy.value &&
    !parsePending.value &&
    !parseCreateUnknown.value &&
    pendingApply.value === null &&
    parseCandidate.value === null &&
    lateCandidate.value === null &&
    (parseTask.value?.status !== 'outcome_unknown' || parseAck.value) &&
    (retainedTask.value === null || parseAck.value),
)

const draftActive = computed(
  () =>
    JSON.stringify(snapshot()) !== JSON.stringify(confirmed.value) ||
    preview.value !== null ||
    previewing.value ||
    applying.value ||
    pendingApply.value !== null ||
    importText.value.trim() !== '' ||
    parsePending.value ||
    parseCandidateBusy.value ||
    parseRecoveryBusy.value ||
    parseCreateUnknown.value ||
    parseTask.value?.status === 'outcome_unknown' ||
    parseCandidate.value !== null ||
    lateCandidate.value !== null,
)
// The watcher is the single source of truth for the parent's draft state (no
// manual emit can leave a stale ``true`` after the pending apply clears).
watch(draftActive, (value) => emit('draft-active', value), { immediate: true })

/** Inputs are disabled while frozen/loading/unresolved/in-flight. */
function inputsBlocked(): boolean {
  return (
    props.frozen === true ||
    !loaded.value ||
    pendingApply.value !== null ||
    parsePending.value ||
    parseCandidateBusy.value ||
    parseRecoveryBusy.value ||
    parseCreateUnknown.value ||
    parseTask.value?.status === 'outcome_unknown'
  )
}

/** A recovery write only needs the freeze/loaded guard, never the pending
 *  guard (otherwise the same-key re-submit could never run). */
function recoveryBlocked(): boolean {
  return props.frozen === true || !loaded.value || applying.value
}

function changeObject(): Record<string, unknown> {
  return {
    kind: 'class_games',
    locations: locations.value.map((location) => ({
      kind: location.kind,
      name: location.name,
      guidance: location.guidance,
    })),
    game_scope: gameScope.value === '' ? null : gameScope.value,
    guidance: guidance.value === '' ? null : guidance.value,
  }
}

/**
 * Consume only a known adjacent ordinary-setting commit from SettingsView.
 * That commit cannot have changed class-game data, but any existing preview,
 * pending apply or in-flight request stays bound to its original version so a
 * genuinely external change still surfaces as an explicit conflict.
 */
function applyKnownCommittedConfig(): boolean {
  const commit = props.committedConfigVersion
  const cache = current.value
  if (!commit || !cache) return false
  if (preview.value || pendingApply.value || previewing.value || applying.value) {
    return false
  }
  if (cache.config_version !== commit.from) return false
  if (commit.to !== commit.from + 1) return false
  current.value = { ...cache, config_version: commit.to }
  return true
}

watch(
  () => props.committedConfigVersion,
  () => {
    applyKnownCommittedConfig()
  },
  { immediate: true },
)

/**
 * Rebase the live draft from a fresh server revision only where it still equals
 * the caller's baseline; ``confirmed`` becomes the REAL fresh server state.
 */
function rebaseFrom(fresh: ClassGames, baseline: GameSnapshot | null): void {
  if (!baseline) {
    locations.value = fresh.change.locations.map((location) => ({ ...location }))
    gameScope.value = fresh.change.game_scope ?? ''
    guidance.value = fresh.change.guidance ?? ''
  } else {
    if (JSON.stringify(locations.value) === JSON.stringify(baseline.locations)) {
      locations.value = fresh.change.locations.map((location) => ({ ...location }))
    }
    if (gameScope.value === baseline.game_scope) {
      gameScope.value = fresh.change.game_scope ?? ''
    }
    if (guidance.value === baseline.guidance) {
      guidance.value = fresh.change.guidance ?? ''
    }
  }
  current.value = fresh
  confirmed.value = {
    locations: fresh.change.locations.map((location) => ({ ...location })),
    game_scope: fresh.change.game_scope ?? '',
    guidance: fresh.change.guidance ?? '',
  }
  preview.value = null
  inputSeq += 1
  applyKnownCommittedConfig()
}

async function load(): Promise<void> {
  const baseline = confirmed.value
  try {
    const data = await apiGet<ClassGames>('/api/local/config/class-games')
    rebaseFrom(data, baseline)
    loaded.value = true
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.message : `读取班级游戏配置失败：${String(err)}`
  }
}

function stopParsePolling(): void {
  if (parseTimer !== null) {
    clearTimeout(parseTimer)
    parseTimer = null
  }
}

function clearImportState(options: { keepRetained?: boolean } = {}): void {
  stopParsePolling()
  parseSeq += 1
  candidateLoadSeq += 1
  importText.value = ''
  parseTask.value = null
  parseCandidate.value = null
  parseRequestId.value = ''
  parseExpectedVersion.value = null
  parseSubmittedText.value = ''
  parseKnownTaskId.value = ''
  parseError.value = ''
  parseNotice.value = ''
  parseBusy.value = false
  parseCandidateBusy.value = false
  parseRecoveryBusy.value = false
  parseCreateUnknown.value = false
  parseAck.value = false
  latestCandidateId.value = ''
  lateCandidate.value = null
  if (!options.keepRetained) retainedTask.value = null
  latestTaskRecovered.value = false
}

function applyImportCandidate(candidate: ConfigAICandidate): void {
  locations.value = candidate.raw_candidate.locations.map((location) => ({
    kind: location.kind,
    name: location.name,
    guidance: location.guidance ?? null,
  }))
  gameScope.value = candidate.raw_candidate.game_scope ?? ''
  guidance.value = candidate.raw_candidate.guidance ?? ''
  preview.value = null
  inputSeq += 1
  errorText.value = ''
}

interface ParseCandidateGuard {
  seq: number
  taskId: string
  expectedVersion: number | null
  inputSeq: number
  submittedText: string
}

function candidateGuard(): ParseCandidateGuard {
  return {
    seq: parseSeq,
    taskId: parseTask.value?.task_id ?? parseKnownTaskId.value,
    expectedVersion: parseTask.value?.config_version ?? parseExpectedVersion.value,
    inputSeq,
    submittedText: parseSubmittedText.value,
  }
}

function candidateGuardStillCurrent(guard: ParseCandidateGuard): boolean {
  return (
    guard.seq === parseSeq &&
    (parseTask.value === null || guard.taskId === '' || parseTask.value.task_id === guard.taskId) &&
    guard.expectedVersion !== null &&
    current.value?.config_version === guard.expectedVersion &&
    inputSeq === guard.inputSeq &&
    importText.value === guard.submittedText
  )
}

async function loadParseCandidate(
  candidateId: string,
  options: { forceLate?: boolean } = {},
): Promise<void> {
  if (parseCandidateBusy.value) return
  const guard = candidateGuard()
  if (options.forceLate) guard.inputSeq = -1
  const loadId = ++candidateLoadSeq
  parseCandidateBusy.value = true
  try {
    const candidate = await apiGet<ConfigAICandidate>(
      `/api/local/config/class-games/ai-candidates/${pathSegment(candidateId)}`,
    )
    if (guard.seq !== parseSeq) return
    if (
      parseTask.value !== null &&
      guard.taskId !== '' &&
      parseTask.value.task_id !== guard.taskId
    ) {
      return
    }
    const expected = guard.expectedVersion
    if (
      candidate.source.config_version !== null &&
      (candidate.source.config_version !== expected ||
        candidate.source.config_version !== current.value?.config_version)
    ) {
      latestCandidateId.value = candidateId
      parseError.value =
        '配置版本已变化：候选未自动写入，请重新读取配置后再解析或读取最近候选'
      return
    }
    if (!candidateGuardStillCurrent(guard)) {
      lateCandidate.value = candidate
      parseNotice.value =
        '候选已到达，但当前游戏配置已有更晚输入：未自动覆盖。请核对后显式载入，或保留当前编辑。'
      parseError.value = ''
      return
    }
    parseCandidate.value = candidate
    applyImportCandidate(candidate)
    lateCandidate.value = null
    parseNotice.value = '已生成结构化候选：请核对并修改字段，再预览确认；确认前不会改写已保存配置。'
    parseError.value = ''
  } catch (err) {
    if (guard.seq !== parseSeq) return
    latestCandidateId.value = candidateId
    parseError.value =
      err instanceof ApiError ? err.message : `读取解析候选失败：${String(err)}`
  } finally {
    if (loadId === candidateLoadSeq) parseCandidateBusy.value = false
  }
}

function useLateCandidate(): void {
  const candidate = lateCandidate.value
  if (!candidate) return
  if (
    candidate.source.config_version !== null &&
    candidate.source.config_version !== current.value?.config_version
  ) {
    latestCandidateId.value = candidate.candidate_id
    lateCandidate.value = null
    parseError.value = '配置版本已变化：晚到候选不能载入，请重新读取配置后再解析'
    return
  }
  parseCandidate.value = candidate
  applyImportCandidate(candidate)
  lateCandidate.value = null
  parseNotice.value = '已载入晚到候选；请核对后预览确认。'
  parseError.value = ''
}

function scheduleParsePoll(): void {
  stopParsePolling()
  const taskId = parseTask.value?.task_id
  if (!taskId || !parsePending.value) return
  parseTimer = setTimeout(async () => {
    parseTimer = null
    if (parseTask.value?.task_id !== taskId) return
    try {
      const task = await apiGet<ConfigAITask>(
        `/api/local/config/class-games/ai-tasks/${pathSegment(taskId)}`,
      )
      if (parseTask.value?.task_id !== taskId) return
      parseTask.value = task
      if (task.status === 'succeeded') {
        if (task.candidate_id) {
          if (latestTaskRecovered.value) {
            latestCandidateId.value = task.candidate_id
            parseNotice.value =
              '最近一次解析已完成，但当前页面已有编辑：候选未自动覆盖。请核对后显式读取最近候选。'
          } else {
            await loadParseCandidate(task.candidate_id)
          }
        } else {
          parseError.value = '解析完成但没有候选结果，请保留原文后重试'
        }
      } else if (
        ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(task.status)
      ) {
        scheduleParsePoll()
      } else if (task.status === 'outcome_unknown') {
        parseError.value =
          '解析结果不明：可能已处理；不会自动重发，请核对结果或明确确认后重新解析'
      } else if (task.status === 'paused' || task.status === 'failed') {
        parseError.value = parseReasonText.value || '解析未完成，请查看状态后重试'
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        parseError.value = '未找到解析任务：不会自动重发，请保留原文后明确重试'
        return
      }
      parseError.value = '查询解析状态暂不可用：结果仍待核对，请稍后重试'
      scheduleParsePoll()
    }
  }, 1200)
}

async function loadLatestParse(): Promise<void> {
  const seq = parseSeq
  try {
    const data = await apiGet<{ task: ConfigAITask | null }>(
      '/api/local/config/class-games/ai-tasks/latest',
    )
    if (seq !== parseSeq) return
    if (!data.task) return
    parseTask.value = data.task
    latestTaskRecovered.value = true
    if (['pending', 'claimed', 'dispatching', 'retry_wait'].includes(data.task.status)) {
      scheduleParsePoll()
      return
    }
    if (data.task.status === 'succeeded' && data.task.candidate_id) {
      latestCandidateId.value = data.task.candidate_id
      return
    }
    if (data.task.status === 'outcome_unknown') {
      // A terminal unknown task is retained for read-only reopening; it must
      // not block the current manual configuration draft or force a resend.
      retainedTask.value = data.task
      parseTask.value = null
      return
    } else if (data.task.status === 'paused' || data.task.status === 'failed') {
      parseError.value = parseReasonText.value || '最近一次解析未完成'
    }
  } catch {
    // A read-only latest-status probe never blocks the manual editor.
  }
}

async function startParse(): Promise<void> {
  if (
    parseBusy.value ||
    parseCandidateBusy.value ||
    parseRecoveryBusy.value ||
    parsePending.value ||
    parseCreateUnknown.value
  ) {
    return
  }
  if (!loaded.value || !current.value) return
  if (!importText.value.trim()) {
    parseError.value = '请先粘贴区域／专用室／户外场地与限制'
    return
  }
  if (parseCandidate.value) {
    parseError.value = '已有解析候选：请先核对预览确认或取消编辑'
    return
  }
  if (lateCandidate.value) {
    parseError.value = '有晚到候选待核对：请先载入或取消，不能直接开始新解析'
    return
  }
  if (
    (parseTask.value?.status === 'outcome_unknown' || retainedTask.value !== null) &&
    !parseAck.value
  ) {
    parseError.value = '上次解析结果不明：请确认可能重复处理或计费后再重新解析'
    return
  }
  if (
    JSON.stringify(snapshot()) !== JSON.stringify(confirmed.value) ||
    preview.value !== null
  ) {
    parseError.value = '当前还有未确认的游戏配置修改：请先预览确认或取消编辑后再 AI 解析'
    return
  }
  const sourceText = importText.value
  const requestId = crypto.randomUUID()
  const expectedVersion = current.value.config_version
  const seq = ++parseSeq
  parseRequestId.value = requestId
  parseExpectedVersion.value = expectedVersion
  parseSubmittedText.value = sourceText
  parseKnownTaskId.value = ''
  parseTask.value = null
  parseCandidate.value = null
  latestCandidateId.value = ''
  lateCandidate.value = null
  retainedTask.value = null
  latestTaskRecovered.value = false
  parseCreateUnknown.value = false
  parseAck.value = false
  parseError.value = ''
  parseNotice.value = ''
  parseBusy.value = true
  try {
    const task = await apiPost<ConfigAITask>(
      '/api/local/config/class-games/ai-tasks',
      {
        request_id: requestId,
        expected_config_version: expectedVersion,
        source_text: sourceText,
      },
    )
    if (seq !== parseSeq) return
    parseKnownTaskId.value = task.task_id
    parseTask.value = task
    if (task.status === 'succeeded' && task.candidate_id) {
      await loadParseCandidate(task.candidate_id)
    } else if (
      ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(task.status)
    ) {
      scheduleParsePoll()
    } else if (task.status === 'outcome_unknown') {
      parseError.value =
        '解析结果不明：可能已处理；不会自动重发，请核对结果或明确确认后重新解析'
    } else if (task.status === 'paused' || task.status === 'failed') {
      parseError.value = parseReasonText.value || '解析未完成，请查看状态后重试'
    }
  } catch (err) {
    if (seq !== parseSeq) return
    if (isIndeterminate(err)) {
      parseCreateUnknown.value = true
      parseError.value =
        '解析请求结果未知：原文已保留；不会自动重发，请查询解析结果或重试同一请求'
    } else if (err instanceof ApiError) {
      if (err.code === 'CONFIG_VERSION_CONFLICT') {
        parseError.value = '配置已更新：已重新读取，请核对后再解析，原文已保留'
        void load()
      } else {
        parseError.value = err.message
      }
    } else {
      parseError.value = `解析失败：${String(err)}`
    }
  } finally {
    if (seq === parseSeq) parseBusy.value = false
  }
}

async function refreshParseTask(): Promise<void> {
  const taskId = parseTask.value?.task_id ?? parseKnownTaskId.value
  if (!taskId || parseBusy.value || parseRecoveryBusy.value) return
  const seq = ++parseSeq
  parseRecoveryBusy.value = true
  parseError.value = ''
  try {
    const task = await apiGet<ConfigAITask>(
      `/api/local/config/class-games/ai-tasks/${pathSegment(taskId)}`,
    )
    if (seq !== parseSeq) return
    parseTask.value = task
    if (task.status === 'succeeded' && task.candidate_id) {
      await loadParseCandidate(task.candidate_id)
    } else if (
      ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(task.status)
    ) {
      scheduleParsePoll()
    } else if (task.status === 'outcome_unknown') {
      parseError.value =
        '解析结果不明：可能已处理；不会自动重发，可结束本次编辑并保留原任务供查询'
    } else if (task.status === 'paused' || task.status === 'failed') {
      parseError.value = parseReasonText.value || '解析未完成，请查看状态后重试'
    }
  } catch (err) {
    if (seq !== parseSeq) return
    parseError.value =
      err instanceof ApiError ? err.message : `查询解析状态失败：${String(err)}`
  } finally {
    if (seq === parseSeq) parseRecoveryBusy.value = false
  }
}

async function queryParseCreate(): Promise<void> {
  if (!parseRequestId.value || parseBusy.value || parseRecoveryBusy.value) return
  const seq = ++parseSeq
  parseRecoveryBusy.value = true
  parseError.value = ''
  try {
    let taskId = parseKnownTaskId.value
    if (!taskId) {
      const query = await queryAiReceipt(parseRequestId.value)
      if (seq !== parseSeq) return
      if (query.state !== 'found') {
        parseError.value = receiptMessage(query)
        return
      }
      const found = query.result.task_id
      if (typeof found !== 'string' || !found) {
        parseError.value = '解析回执缺少任务标识：原文已保留，不会自动重发'
        return
      }
      taskId = found
      parseKnownTaskId.value = found
    }
    // Keep the recovery UI until the task read succeeds.  A 503 here must
    // not clear parseCreateUnknown or re-open a new submission.
    const task = await apiGet<ConfigAITask>(
      `/api/local/config/class-games/ai-tasks/${pathSegment(taskId)}`,
    )
    if (seq !== parseSeq) return
    parseCreateUnknown.value = false
    parseTask.value = task
    if (task.status === 'succeeded' && task.candidate_id) {
      await loadParseCandidate(task.candidate_id)
    } else if (
      ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(task.status)
    ) {
      scheduleParsePoll()
    } else if (task.status === 'outcome_unknown') {
      parseError.value =
        '解析结果不明：可能已处理；不会自动重发，可结束本次编辑并保留原任务供查询'
    } else if (task.status === 'paused' || task.status === 'failed') {
      parseError.value = parseReasonText.value || '解析未完成，请查看状态后重试'
    }
  } catch (err) {
    if (seq !== parseSeq) return
    parseError.value = parseKnownTaskId.value
      ? '原解析任务已确定，但任务状态暂不可读：原请求和原文均保留，请再次只读查询；不会换键重发'
      : err instanceof ApiError
        ? err.message
        : `读取解析任务失败：${String(err)}`
    // parseCreateUnknown stays true until a task read succeeds.
  } finally {
    if (seq === parseSeq) parseRecoveryBusy.value = false
  }
}

async function retryParseCreate(): Promise<void> {
  if (
    !parseRequestId.value ||
    parseExpectedVersion.value === null ||
    parseBusy.value ||
    parseRecoveryBusy.value ||
    parseKnownTaskId.value
  ) {
    return
  }
  const seq = ++parseSeq
  parseRecoveryBusy.value = true
  parseError.value = ''
  try {
    const task = await apiPost<ConfigAITask>(
      '/api/local/config/class-games/ai-tasks',
      {
        request_id: parseRequestId.value,
        expected_config_version: parseExpectedVersion.value,
        source_text: parseSubmittedText.value,
      },
    )
    if (seq !== parseSeq) return
    parseCreateUnknown.value = false
    parseKnownTaskId.value = task.task_id
    parseTask.value = task
    if (task.status === 'succeeded' && task.candidate_id) {
      await loadParseCandidate(task.candidate_id)
    } else if (
      ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(task.status)
    ) {
      scheduleParsePoll()
    } else if (task.status === 'outcome_unknown') {
      parseError.value =
        '解析结果不明：可能已处理；不会自动重发，可结束本次编辑并保留原任务供查询'
    } else if (task.status === 'paused' || task.status === 'failed') {
      parseError.value = parseReasonText.value || '解析未完成，请查看状态后重试'
    }
  } catch (err) {
    if (seq !== parseSeq) return
    if (isIndeterminate(err)) {
      parseError.value =
        '重试仍未确认：原文已保留；不会自动重发，请稍后再次查询结果'
    } else if (err instanceof ApiError) {
      if (err.code === 'CONFIG_VERSION_CONFLICT') {
        parseError.value = '配置已更新：已重新读取，请核对后再解析，原文已保留'
        void load()
      } else {
        parseError.value = err.message
      }
    } else {
      parseError.value = `重试失败：${String(err)}`
    }
  } finally {
    if (seq === parseSeq) parseRecoveryBusy.value = false
  }
}

async function loadLatestCandidate(): Promise<void> {
  if (!latestCandidateId.value) return
  const draftDirty =
    JSON.stringify(snapshot()) !== JSON.stringify(confirmed.value) ||
    importText.value.trim() !== ''
  await loadParseCandidate(latestCandidateId.value, { forceLate: draftDirty })
}

function addLocation(): void {
  if (inputsBlocked()) return
  locations.value.push({ kind: 'area', name: '', guidance: null })
  invalidate()
}

function removeLocation(index: number): void {
  if (inputsBlocked()) return
  locations.value.splice(index, 1)
  invalidate()
}

function invalidate(): void {
  inputSeq += 1
  preview.value = null
}

async function previewChange(): Promise<void> {
  if (inputsBlocked() || previewing.value || applying.value || !current.value) return
  applyKnownCommittedConfig()
  const names = locations.value.map((location) => location.name.trim())
  if (names.some((name) => name === '')) {
    errorText.value = '地点名称不能为空'
    return
  }
  const seq = inputSeq
  previewing.value = true
  errorText.value = ''
  messageText.value = ''
  try {
    const result = await apiPost<ConfigPreview>('/api/local/config/preview', {
      expected_config_version: current.value.config_version,
      change: changeObject(),
    })
    if (seq !== inputSeq) return
    preview.value = result
  } catch (err) {
    handleError(err)
  } finally {
    previewing.value = false
  }
}

async function finishApplied(submitted: GameSnapshot, version: number | null): Promise<void> {
  const fresh = await apiGet<ClassGames>('/api/local/config/class-games')
  rebaseFrom(fresh, submitted)
  pendingApply.value = null
  clearImportState()
  messageText.value = `班级游戏配置已应用（新配置版本 v${
    version ?? fresh.config_version
  }，游戏修订 ${fresh.game_revision_id}）`
  emit('applied')
}

async function applyPreview(): Promise<void> {
  if (inputsBlocked() || !preview.value || applying.value) return
  if (!preview.value.changed) {
    ElMessage.info('没有实际修改')
    preview.value = null
    return
  }
  const submitted = snapshot()
  const requestId = crypto.randomUUID()
  const body: Record<string, unknown> = {
    request_id: requestId,
    expected_config_version: preview.value.expected_config_version,
    change: preview.value.normalized_change,
    preview_token: preview.value.preview_token,
  }
  applying.value = true
  errorText.value = ''
  try {
    const result = await apiPost<{ config_version: number }>('/api/local/config/apply', body)
    await finishApplied(submitted, result.config_version)
  } catch (err) {
    if (isIndeterminate(err)) {
      // Keep the COMPLETE original request/body; block leaving until resolved.
      pendingApply.value = { requestId, body, submitted }
      errorText.value =
        '应用结果未知：已保留原提交，请查询提交结果，或用同一请求 ID 与请求体重试原提交'
      return
    }
    handleError(err)
  } finally {
    applying.value = false
  }
}

async function queryApply(): Promise<void> {
  const pending = pendingApply.value
  if (!pending) return
  try {
    const result = await apiGet<Record<string, unknown>>(
      `/api/local/config/operations/${pathSegment(pending.requestId)}`,
    )
    // A late receipt must never apply to a newer pending operation.
    if (pendingApply.value?.requestId !== pending.requestId) return
    await finishApplied(pending.submitted, Number(result.config_version ?? 0) || null)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorText.value = '尚未查到已提交结果：请稍后再次查询，或用同一请求重试原提交'
    } else {
      errorText.value = '查询暂不可用：结果仍待核对，请稍后重试'
    }
  }
}

async function resubmitApply(): Promise<void> {
  const pending = pendingApply.value
  if (!pending || recoveryBlocked()) return
  applying.value = true
  errorText.value = ''
  try {
    const result = await apiPost<{ config_version: number }>(
      '/api/local/config/apply',
      pending.body,
    )
    await finishApplied(pending.submitted, result.config_version)
  } catch (err) {
    if (isIndeterminate(err)) {
      errorText.value = '重试仍未确认：请稍后再次查询提交结果'
      return
    }
    handleError(err)
  } finally {
    applying.value = false
  }
}

function handleError(err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'CONFIG_VERSION_CONFLICT' || err.code === 'CONFIG_PREVIEW_STALE') {
      errorText.value = '配置已被其他操作更新：已重新读取，请比较后重新预览确认'
      void load()
      return
    }
    errorText.value = err.message
    return
  }
  errorText.value = `操作失败：${String(err)}`
}

async function queryRetainedTask(): Promise<void> {
  if (!retainedTask.value || parseRecoveryBusy.value) return
  parseTask.value = retainedTask.value
  retainedTask.value = null
  await refreshParseTask()
}

function cancelDraft(): void {
  if (
    props.frozen ||
    applying.value ||
    pendingApply.value ||
    parseBusy.value ||
    parseCandidateBusy.value ||
    parseRecoveryBusy.value ||
    parsePending.value ||
    parseCreateUnknown.value
  ) {
    if (pendingApply.value) {
      errorText.value = '应用结果待核对：不能取消丢弃，请先查询提交结果'
    } else if (parseCreateUnknown.value) {
      errorText.value = '解析请求结果待核对：不能取消丢弃，请先查询解析结果'
    } else if (parseCandidateBusy.value) {
      errorText.value = '正在读取解析候选：不能取消丢弃，请稍后重试'
    } else if (parseRecoveryBusy.value) {
      errorText.value = '正在核对解析状态：不能取消丢弃，请稍后重试'
    } else if (parsePending.value) {
      errorText.value = 'AI 正在解析：不能取消丢弃，请等待或稍后查询状态'
    }
    return
  }
  // A terminal outcome_unknown task is retained for read-only reopening.  It
  // must not trap the teacher in the config editor or force a new paid request.
  const retained =
    parseTask.value?.status === 'outcome_unknown' ? { ...parseTask.value } : null
  const existingRetained = retainedTask.value
  locations.value = current.value ? current.value.change.locations.map((l) => ({ ...l })) : []
  gameScope.value = current.value?.change.game_scope ?? ''
  guidance.value = current.value?.change.guidance ?? ''
  preview.value = null
  errorText.value = ''
  messageText.value = ''
  inputSeq += 1
  clearImportState({ keepRetained: true })
  if (retained) {
    retainedTask.value = retained
  } else if (existingRetained) {
    retainedTask.value = existingRetained
  }
  ElMessage.info('已取消班级游戏配置编辑')
}

function describeValue(value: unknown): string {
  if (value === null || value === undefined) return '（空）'
  if (typeof value === 'string') return value === '' ? '（空字符串）' : value
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'object' && item ? describeValue(item) : String(item)))
      .join('；')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}=${describeValue(item)}`)
      .join('，')
  }
  return String(value)
}

const beforeText = computed(() => (preview.value ? describeValue(preview.value.before) : ''))
const afterText = computed(() => (preview.value ? describeValue(preview.value.after) : ''))

onMounted(() => {
  ;(window as unknown as { __d1GameConfig?: object }).__d1GameConfig = {
    current: () => current.value,
    loaded: () => loaded.value,
    draftActive: () => draftActive.value,
    draftTargets: () => draftTargets(),
    previewVisible: () => preview.value !== null,
    beforeText: () => beforeText.value,
    afterText: () => afterText.value,
    errorText: () => errorText.value,
    messageText: () => messageText.value,
    pendingApply: () => pendingApply.value,
    locations: () => locations.value,
    gameScope: () => gameScope.value,
    guidance: () => guidance.value,
    setGameScope: (value: string) => {
      if (inputsBlocked()) return
      gameScope.value = value
      invalidate()
    },
    setGuidance: (value: string) => {
      if (inputsBlocked()) return
      guidance.value = value
      invalidate()
    },
    addLocation: () => addLocation(),
    setLocation: (index: number, name: string, kind: GameLocation['kind'], locationGuidance: string | null) => {
      if (inputsBlocked()) return
      locations.value[index] = { kind, name, guidance: locationGuidance }
      invalidate()
    },
    removeLocation: (index: number) => removeLocation(index),
    previewChange: () => previewChange(),
    applyPreview: () => applyPreview(),
    queryApply: () => queryApply(),
    resubmitApply: () => resubmitApply(),
    cancelDraft: () => cancelDraft(),
    load: () => load(),
    importText: () => importText.value,
    setImportText: (value: string) => {
      if (inputsBlocked()) return
      importText.value = value
    },
    parseTask: () => parseTask.value,
    parseCandidate: () => parseCandidate.value,
    parseError: () => parseError.value,
    parseNotice: () => parseNotice.value,
    parsePending: () => parsePending.value,
    parseCandidateBusy: () => parseCandidateBusy.value,
    canStartParse: () => canStartParse.value,
    invalidate: () => invalidate(),
    parseCreateUnknown: () => parseCreateUnknown.value,
    parseKnownTaskId: () => parseKnownTaskId.value,
    lateCandidate: () => lateCandidate.value,
    retainedTask: () => retainedTask.value,
    useLateCandidate: () => useLateCandidate(),
    queryRetainedTask: () => queryRetainedTask(),
    startParse: () => startParse(),
    queryParseCreate: () => queryParseCreate(),
    refreshParseTask: () => refreshParseTask(),
    retryParseCreate: () => retryParseCreate(),
    loadLatestCandidate: () => loadLatestCandidate(),
    parseAck: (value: boolean) => {
      parseAck.value = value
    },
  }
  void load().then(() => {
    if (loaded.value) void loadLatestParse()
  })
})

onBeforeUnmount(() => {
  stopParsePolling()
  parseSeq += 1
  candidateLoadSeq += 1
  emit('draft-active', false)
  delete (window as unknown as { __d1GameConfig?: object }).__d1GameConfig
})
/** Focus the first class-game control or the card itself. */
function focusDraftTarget(): void {
  const selector = '[data-d1="game-config"]'
  const element = document.querySelector(selector) as HTMLElement | null
  if (!element) return
  element.scrollIntoView?.({ block: 'center' })
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus?.()
}

defineExpose({ draftTargets, focusDraftTarget })
</script>

<template>
  <el-card class="section" shadow="never" data-d1="game-config">
    <template #header>
      <div class="head">
        <span>班级游戏配置（区域 / 专用室 / 户外场地与限制）</span>
        <el-tag v-if="current" size="small" type="info">
          当前修订 #{{ current.revision_no }} · 配置版本 v{{ current.config_version }}
        </el-tag>
        <el-tag v-if="pendingApply" size="small" type="danger">有未决应用</el-tag>
      </div>
    </template>
    <p class="muted">
      为空表示“未设置班级游戏配置”，其他活动生成时会说明为一般建议；配置改变不会改写旧计划或自动生成新候选。
    </p>

    <div class="import-block" data-d1="game-import">
      <div class="import-head">
        <strong>整段粘贴并由 AI 解析</strong>
        <el-tag v-if="parseTask" size="small" type="info" data-d1="game-import-status-tag">
          {{ parseStatusText }}
        </el-tag>
      </div>
      <p class="muted">
        粘贴区域／专用室／户外场地与限制；AI 只生成结构化候选，确认前不会改写已保存配置。缺项留空，由教师核对修改。
      </p>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="6"
        maxlength="20000"
        show-word-limit
        :disabled="frozen || !loaded || parsePending || parseCandidateBusy || parseRecoveryBusy || parseCreateUnknown || parseBusy || pendingApply !== null || !!parseCandidate"
        placeholder="例如：区域：建构区——限 4 人；专用室：图书室——安静阅读；户外：东操场——大型器械，注意间距……"
        data-d1="game-import-text"
      />
      <div class="row">
        <el-button
          type="primary"
          data-d1="game-import-parse"
          :loading="parseBusy"
          :disabled="!canStartParse"
          @click="startParse"
        >
          AI 解析
        </el-button>
        <el-button
          v-if="latestCandidateId && !parseCandidate"
          data-d1="game-import-load-latest"
          :disabled="frozen || parsePending || pendingApply !== null"
          @click="loadLatestCandidate"
        >
          读取最近解析候选
        </el-button>
        <el-button
          v-if="parseCreateUnknown"
          data-d1="game-import-query"
          :loading="parseRecoveryBusy"
          :disabled="parseBusy || parseRecoveryBusy"
          @click="queryParseCreate"
        >
          {{ parseKnownTaskId ? '再次查询原任务' : '查询解析结果' }}
        </el-button>
        <el-button
          v-if="parseCreateUnknown && !parseKnownTaskId"
          data-d1="game-import-retry"
          :loading="parseRecoveryBusy"
          :disabled="parseBusy || parseRecoveryBusy"
          @click="retryParseCreate"
        >
          重试原解析请求（同一请求）
        </el-button>
      </div>
      <p v-if="parseTask" class="muted" data-d1="game-import-status">
        解析状态：{{ parseStatusText }}
        <span v-if="parseReasonText"> · {{ parseReasonText }}</span>
        <el-button
          v-if="!parsePending"
          size="small"
          text
          data-d1="game-import-refresh"
          :disabled="parseBusy"
          @click="refreshParseTask"
        >
          查询解析状态
        </el-button>
      </p>
      <el-checkbox
        v-if="parseTask?.status === 'outcome_unknown' || retainedTask"
        v-model="parseAck"
        data-d1="game-import-ack"
      >
        我确认重新解析可能重复处理或计费
      </el-checkbox>
      <el-alert
        v-if="retainedTask"
        type="info"
        :closable="false"
        class="import-alert"
        data-d1="game-import-retained"
        title="最近一次解析结果不明，原任务已保留；不会自动重发，也不会改写配置。"
      >
        <p class="muted" data-d1="game-import-retained-id">任务 ID：{{ retainedTask.task_id }}</p>
        <el-button
          size="small"
          data-d1="game-import-retained-query"
          :disabled="parseRecoveryBusy"
          @click="queryRetainedTask"
        >
          查询原解析任务
        </el-button>
      </el-alert>
      <el-alert
        v-if="lateCandidate"
        type="warning"
        :closable="false"
        class="import-alert"
        data-d1="game-import-late"
        title="候选已到达，但当前游戏配置已有更晚输入；未自动覆盖。"
      >
        <el-button
          size="small"
          data-d1="game-import-late-load"
          @click="useLateCandidate"
        >
          核对并载入该候选
        </el-button>
      </el-alert>
      <el-alert
        v-if="parseError"
        type="warning"
        :closable="false"
        class="import-alert"
        data-d1="game-import-error"
        :title="parseError"
      />
      <el-alert
        v-if="parseNotice"
        type="success"
        :closable="false"
        class="import-alert"
        data-d1="game-import-notice"
        :title="parseNotice"
      />
    </div>

    <div v-for="(location, index) in locations" :key="index" class="location-row" data-d1="game-location">
      <el-select v-model="location.kind" size="small" class="kind-select" :disabled="inputsBlocked()" @change="invalidate">
        <el-option label="区域" value="area" />
        <el-option label="专用室" value="special_room" />
        <el-option label="户外场地" value="outdoor" />
      </el-select>
      <el-input v-model="location.name" size="small" placeholder="地点名称（1–80 字）" maxlength="80" class="name-input" :disabled="inputsBlocked()" @input="invalidate" />
      <el-input v-model="location.guidance" size="small" placeholder="该地点的简短限制/指导（可空）" maxlength="2000" class="guide-input" :disabled="inputsBlocked()" @input="invalidate" />
      <el-button size="small" text type="danger" :disabled="inputsBlocked()" @click="removeLocation(index)">移除</el-button>
    </div>
    <el-button size="small" data-d1="game-add-location" :disabled="inputsBlocked()" @click="addLocation">添加地点</el-button>
    <div class="field"><label>游戏范围（可空）</label><el-input v-model="gameScope" type="textarea" :rows="2" maxlength="8000" :disabled="inputsBlocked()" @input="invalidate" /></div>
    <div class="field"><label>通用限制 / 指导（可空）</label><el-input v-model="guidance" type="textarea" :rows="2" maxlength="8000" :disabled="inputsBlocked()" @input="invalidate" /></div>
    <div class="row">
      <el-button size="small" data-d1="game-preview" :loading="previewing" :disabled="inputsBlocked()" @click="previewChange">预览修改</el-button>
      <el-button
        size="small"
        type="primary"
        data-d1="game-apply"
        :loading="applying"
        :disabled="inputsBlocked() || !preview || !preview.changed"
        @click="applyPreview"
      >
        确认应用
      </el-button>
      <el-button size="small" data-d1="game-cancel" :disabled="frozen || !!pendingApply || parsePending || parseCreateUnknown || parseCandidateBusy || parseRecoveryBusy" @click="cancelDraft">取消编辑</el-button>
    </div>
    <div v-if="pendingApply" class="pending-block" data-d1="game-pending">
      <span class="muted">应用结果未决（请求 {{ pendingApply.requestId.slice(0, 8) }}…）</span>
      <div class="row">
        <el-button size="small" type="warning" @click="queryApply">查询提交结果</el-button>
        <el-button size="small" type="danger" :loading="applying" @click="resubmitApply">重试原提交（同一请求）</el-button>
      </div>
    </div>
    <div v-if="preview" class="preview-block" data-d1="game-preview-block">
      <el-tag size="small" :type="preview.changed ? 'warning' : 'info'">
        {{ preview.changed ? '有实际修改' : '无实际修改' }}
      </el-tag>
      <p class="muted">修改前：{{ beforeText }}</p>
      <p class="muted">修改后：{{ afterText }}</p>
      <p class="muted">确认后才会生成新的不可变游戏修订；已有计划保留原表头。</p>
    </div>
  </el-card>

  <el-alert v-if="errorText" type="error" :closable="false" class="section" data-d1="game-error" :title="errorText" />
  <el-alert v-if="messageText" type="success" :closable="false" class="section" data-d1="game-message" :title="messageText" />
</template>

<style scoped>
.section {
  margin-top: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.location-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.kind-select {
  width: 120px;
}
.name-input {
  width: 220px;
}
.guide-input {
  width: 340px;
}
.field {
  margin-top: 10px;
}
.field label {
  display: block;
  margin-bottom: 4px;
  font-size: 0.85rem;
  color: var(--kgm-text);
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.pending-block {
  background: color-mix(in srgb, var(--kgm-warning) 12%, var(--kgm-surface));
  border: 1px solid var(--kgm-warning);
  border-radius: 4px;
  padding: 8px 10px;
  margin-top: 10px;
}
.preview-block {
  margin-top: 12px;
}
.import-block {
  border: 1px dashed var(--kgm-border);
  border-radius: 4px;
  padding: 10px;
  margin-top: 12px;
}
.import-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.import-alert {
  margin-top: 8px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
</style>
