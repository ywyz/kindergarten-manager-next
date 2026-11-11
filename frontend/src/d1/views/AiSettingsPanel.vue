<script setup lang="ts">
/**
 * D2 W5 AI settings (engineering spec §5.1/§5.2, product C12/C13/Q7).
 *
 * Repair round (review §6 R08/R09):
 * - every write keeps its COMPLETE original context (method/path/body/request
 *   id); an unknown outcome keeps it pending, blocks leaving and offers only a
 *   read-only receipt query or an explicit same-key/same-body re-submit;
 * - merge is by the actually-submitted field mask: save/adapt merge the
 *   submitted fields, accept merges only the selected fields, reject changes
 *   only the rejected status — other fields/tasks and later input survive;
 * - the initial load is guarded: fields are disabled until their first read
 *   completes, so a late initial response cannot overwrite user text;
 * - the config secret is cleared only when it still equals the submitted one;
 * - a close freeze disables all inputs and mutating methods;
 * - the prompt-package card is read/manual-check only: it never blocks manual
 *   work and an unconfigured source performs no network.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPatch, apiPost, ApiError, pathSegment } from '../client'
import { queryAiReceipt, receiptMessage, isIndeterminate } from '../operations'
import type {
  AiConfig,
  Prompt,
  PromptDefault,
  PromptList,
  PromptPackageStatus,
} from '../types'
import { displayFieldLabel, taskTypeLabel } from '../ai'

const props = defineProps<{ frozen?: boolean }>()

const emit = defineEmits<{
  (e: 'draft-active', active: boolean): void
}>()

type WriteKind = 'config' | 'clear' | 'prompt' | 'accept' | 'reject' | 'adapt'

interface PendingWrite {
  key: string
  label: string
  method: 'PATCH' | 'POST'
  path: string
  body: Record<string, unknown>
  kind: WriteKind
  taskType?: string
  mergedFields?: string[]
  beforeMap?: Record<string, string>
  secretSubmitted?: string
  submittedBase?: string
  submittedModel?: string
  success?: string
}

const config = ref<AiConfig | null>(null)
const configLoaded = ref(false)
const configForm = reactive({ base_url: '', model: '', secret: '' })
const confirmedConfig = ref<{ base_url: string; model: string } | null>(null)
const prompts = ref<Prompt[]>([])
const promptsLoaded = ref(false)
const promptGuides = ref<Record<string, Record<string, string>>>({})
const confirmedGuides = ref<Record<string, Record<string, string>>>({})
const defaults = ref<Record<string, PromptDefault | null>>({})
const acceptFields = ref<Record<string, string[]>>({})
const busy = ref('')
const errorText = ref('')
const messageText = ref('')
const pendingWrites = ref<PendingWrite[]>([])
const promptPackage = ref<PromptPackageStatus | null>(null)
const promptPackageChecking = ref(false)
let promptLoadSeq = 0
let promptLoadInFlight: Promise<void> | null = null

const PROMPT_PACKAGE_LABELS: Record<string, string> = {
  unconfigured: '来源未配置',
  idle: '待检查',
  checking: '正在检查',
  updated: '已更新',
  no_update: '已是最新',
  package: '使用已验证功能包',
  builtin: '使用内置文字',
  cache_missing: '缓存缺失',
  cache_invalid: '缓存校验失败',
  cache_stale: '缓存序号过旧',
  cache_reused: '已恢复缓存包',
  offline: '网络不可用',
  invalid: '校验失败',
  incompatible: '版本不兼容',
  rollback_rejected: '已拒绝旧包',
  sequence_conflict: '序号冲突',
  identity_conflict: '内容冲突',
  rejected: '未启用',
  failed: '启用失败',
}

function promptPackageStateLabel(): string {
  const value = promptPackage.value
  if (!value) return '正在读取…'
  return PROMPT_PACKAGE_LABELS[value.state] ?? value.state
}

function promptPackageVersionText(): string {
  const value = promptPackage.value
  if (!value) return ''
  if (value.active_source !== 'package' || value.release_sequence === null) {
    return '内置文字'
  }
  return `功能包 r${value.release_sequence}`
}

async function loadPromptPackage(): Promise<void> {
  try {
    promptPackage.value = await apiGet<PromptPackageStatus>(
      '/api/local/ai/prompt-package',
    )
  } catch (err) {
    errorText.value =
      err instanceof ApiError
        ? err.message
        : `读取提示词功能包状态失败：${String(err)}`
  }
}

async function checkPromptPackage(): Promise<void> {
  if (guard() || promptPackageChecking.value) return
  promptPackageChecking.value = true
  errorText.value = ''
  messageText.value = ''
  const beforeSequence = promptPackage.value?.release_sequence ?? null
  const beforeActiveSource = promptPackage.value?.active_source ?? null
  try {
    const next = await apiPost<PromptPackageStatus>(
      '/api/local/ai/prompt-package/check',
    )
    promptPackage.value = next
    // A package update or cache fallback changes the server-side effective
    // default.  Re-read the prompts once through the existing merge path;
    // unsaved edits win, viewed defaults and unresolved receipts are left
    // untouched.
    if (
      next.release_sequence !== beforeSequence ||
      next.active_source !== beforeActiveSource
    ) {
      await loadPrompts(true)
    }
    ElMessage.info(next.message)
  } catch (err) {
    errorText.value =
      err instanceof ApiError
        ? err.message
        : `检查提示词更新失败：${String(err)}`
  } finally {
    promptPackageChecking.value = false
  }
}

function promptFor(taskType: string): Prompt | null {
  return prompts.value.find((prompt) => prompt.task_type === taskType) ?? null
}

const PROMPT_GROUPS: Array<{ key: string; label: string; matches: (type: string) => boolean }> = [
  { key: 'daily', label: '日计划', matches: (type) => type.startsWith('daily_') },
  { key: 'weekly', label: '周计划', matches: (type) => type.startsWith('weekly_') },
  { key: 'listening', label: '一对一倾听', matches: (type) => type.startsWith('listening_') },
  { key: 'observation', label: '游戏观察', matches: (type) => type.startsWith('game_observation_') },
  { key: 'curriculum', label: '课程审议', matches: (type) => type.startsWith('curriculum_') },
  { key: 'config', label: '班级游戏配置', matches: (type) => type === 'class_game_config_extract' },
  { key: 'directional', label: '定向修改', matches: (type) => type === 'directional_revision' },
]
function promptGroupKey(taskType: string): string {
  return PROMPT_GROUPS.find((group) => group.matches(taskType))?.key ?? 'other'
}
const promptGroups = computed(() => {
  const groups = new Map<string, { key: string; label: string; items: Prompt[] }>()
  for (const prompt of prompts.value) {
    const key = promptGroupKey(prompt.task_type)
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label: PROMPT_GROUPS.find((group) => group.key === key)?.label ?? '其他提示词',
        items: [],
      })
    }
    groups.get(key)!.items.push(prompt)
  }
  const order = new Map(PROMPT_GROUPS.map((group, index) => [group.key, index]))
  return [...groups.values()].sort(
    (left, right) =>
      (order.get(left.key) ?? Number.MAX_SAFE_INTEGER) -
      (order.get(right.key) ?? Number.MAX_SAFE_INTEGER),
  )
})

/** The required-contract fields, prefilled from the required default. */
function guidanceFromPrompt(prompt: Prompt): Record<string, string> {
  const map: Record<string, string> = {}
  for (const field of prompt.fields) {
    map[field.key] = prompt.guidance[field.key] ?? field.default_text
  }
  return map
}

const configDirty = computed(() => {
  const confirmed = confirmedConfig.value
  if (!confirmed) return false
  return (
    configForm.base_url !== confirmed.base_url ||
    configForm.model !== confirmed.model ||
    configForm.secret !== ''
  )
})

const promptsDirty = computed(() => {
  const taskTypes = new Set([...Object.keys(promptGuides.value), ...Object.keys(confirmedGuides.value)])
  for (const taskType of taskTypes) {
    const current = promptGuides.value[taskType] ?? {}
    const confirmed = confirmedGuides.value[taskType] ?? {}
    const keys = new Set([...Object.keys(current), ...Object.keys(confirmed)])
    for (const key of keys) {
      if ((current[key] ?? '') !== (confirmed[key] ?? '')) return true
    }
  }
  return false
})

/** Structured blocking targets for the settings shell (never parsed text). */
function draftTargets(): string[] {
  const targets: string[] = []
  const pendingKeys = pendingWrites.value.map((write) => write.key)
  const busyKey = busy.value
  const promptBusy =
    busyKey.startsWith('prompt-') ||
    busyKey.startsWith('default-') ||
    busyKey.startsWith('accept-') ||
    busyKey.startsWith('reject-') ||
    busyKey.startsWith('adapt-')
  const configBusy = busyKey === 'config' || busyKey === 'clear'
  if (
    configDirty.value ||
    configBusy ||
    pendingKeys.some((key) => key === 'config' || key === 'clear')
  ) {
    targets.push('ai-config')
  }
  if (
    promptsDirty.value ||
    promptBusy ||
    pendingKeys.some((key) =>
      ['prompt-', 'default-', 'accept-', 'reject-', 'adapt-'].some((prefix) =>
        key.startsWith(prefix),
      ),
    )
  ) {
    targets.push('ai-prompts')
  }
  return targets
}

const draftActive = computed(
  () => configDirty.value || promptsDirty.value || busy.value !== '' || pendingWrites.value.length > 0,
)
watch(draftActive, (value) => emit('draft-active', value), { immediate: true })

function guard(): boolean {
  return props.frozen === true
}

function hasPending(key: string): boolean {
  return pendingWrites.value.some((write) => write.key === key)
}

async function loadConfig(): Promise<void> {
  try {
    const data = await apiGet<AiConfig>('/api/local/ai/config')
    config.value = data
    if (!configLoaded.value) {
      // The first read adopts the server state; later reads never overwrite a
      // live draft (the fields are guarded until the first read anyway).
      configForm.base_url = data.base_url ?? ''
      configForm.model = data.model ?? ''
      configForm.secret = ''
    }
    confirmedConfig.value = { base_url: data.base_url ?? '', model: data.model ?? '' }
    configLoaded.value = true
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.message : `读取 AI 配置失败：${String(err)}`
  }
}

/** Load the prompts, preserving unsent guidance edits (R08). */
async function loadPrompts(force = false): Promise<void> {
  if (!force && promptLoadInFlight) return promptLoadInFlight
  const seq = ++promptLoadSeq
  const task = (async () => {
    try {
      const data = await apiGet<PromptList>('/api/local/ai/prompts?scope=all')
      // A newer load (for example the one started after a package update) owns
      // the state; a late older response must not overwrite it.
      if (seq !== promptLoadSeq) return
      prompts.value = data.items
      const nextLive: Record<string, Record<string, string>> = { ...promptGuides.value }
      const nextConfirmed: Record<string, Record<string, string>> = { ...confirmedGuides.value }
      for (const prompt of data.items) {
        const serverMap = guidanceFromPrompt(prompt)
        const live = promptGuides.value[prompt.task_type]
        const confirmed = confirmedGuides.value[prompt.task_type]
        if (!live || !confirmed) {
          nextLive[prompt.task_type] = { ...serverMap }
        } else {
          const merged = { ...live }
          for (const key of Object.keys(serverMap)) {
            if ((live[key] ?? '') === (confirmed[key] ?? '')) merged[key] = serverMap[key]
            else if (!(key in live)) merged[key] = serverMap[key]
          }
          nextLive[prompt.task_type] = merged
        }
        nextConfirmed[prompt.task_type] = { ...serverMap }
      }
      promptGuides.value = nextLive
      confirmedGuides.value = nextConfirmed
      promptsLoaded.value = true
    } catch (err) {
      if (seq !== promptLoadSeq) return
      errorText.value = err instanceof ApiError ? err.message : `读取指导设置失败：${String(err)}`
    }
  })()
  promptLoadInFlight = task
  try {
    await task
  } finally {
    if (promptLoadInFlight === task) promptLoadInFlight = null
  }
}

/** Merge a saved prompt using the actually-submitted field mask. */
function mergeSavedPrompt(
  saved: Prompt,
  mergedFields: string[],
  beforeMap: Record<string, string>,
): void {
  const serverMap = guidanceFromPrompt(saved)
  const live = { ...(promptGuides.value[saved.task_type] ?? {}) }
  const confirmed = { ...(confirmedGuides.value[saved.task_type] ?? {}) }
  for (const key of mergedFields) {
    if ((live[key] ?? '') === (beforeMap[key] ?? '')) {
      live[key] = serverMap[key]
    }
    confirmed[key] = serverMap[key]
  }
  promptGuides.value = { ...promptGuides.value, [saved.task_type]: live }
  confirmedGuides.value = { ...confirmedGuides.value, [saved.task_type]: confirmed }
  prompts.value = prompts.value.map((prompt) =>
    prompt.task_type === saved.task_type ? saved : prompt,
  )
}

function setGuidanceField(taskType: string, key: string, value: string): void {
  if (guard() || !promptsLoaded.value) return
  const map = { ...(promptGuides.value[taskType] ?? {}) }
  map[key] = value
  promptGuides.value = { ...promptGuides.value, [taskType]: map }
}

// --- unified write protocol --------------------------------------------------

function applyWrite(write: PendingWrite, result: unknown): void {
  if (write.kind === 'config') {
    const saved = result as AiConfig
    config.value = saved
    if (configForm.secret === write.secretSubmitted) configForm.secret = ''
    if (configForm.base_url === write.submittedBase) configForm.base_url = saved.base_url ?? ''
    if (configForm.model === write.submittedModel) configForm.model = saved.model ?? ''
    confirmedConfig.value = { base_url: saved.base_url ?? '', model: saved.model ?? '' }
    messageText.value = 'AI 配置已保存（不会试调用供应商）'
    return
  }
  if (write.kind === 'clear') {
    config.value = result as AiConfig
    // Only clear the secret input when it is still the submitted generation;
    // a secret typed while the clear was in flight is preserved.
    if (configForm.secret === (write.secretSubmitted ?? '')) configForm.secret = ''
    messageText.value = '已清除密钥；在途请求不会被撤回，供应商可能仍在处理'
    return
  }
  mergeSavedPrompt(
    result as Prompt,
    write.mergedFields ?? [],
    write.beforeMap ?? {},
  )
  messageText.value = write.success ?? '已保存'
}

function addPending(write: PendingWrite): void {
  const next = pendingWrites.value.filter((item) => item.key !== write.key)
  next.push(write)
  pendingWrites.value = next
}

function removePending(key: string): void {
  pendingWrites.value = pendingWrites.value.filter((item) => item.key !== key)
}

async function perform(write: PendingWrite): Promise<void> {
  // Same method/path/body/request id for the first attempt and any re-submit.
  const request =
    write.method === 'PATCH'
      ? apiPatch<unknown>(write.path, write.body)
      : apiPost<unknown>(write.path, write.body)
  const result = await request
  removePending(write.key)
  applyWrite(write, result)
}

async function runWrite(write: PendingWrite): Promise<void> {
  if (guard() || busy.value) return
  busy.value = write.key
  errorText.value = ''
  messageText.value = ''
  try {
    await perform(write)
  } catch (err) {
    if (isIndeterminate(err)) {
      addPending(write)
      errorText.value =
        '提交结果未知：请查询提交结果，或用同一请求 ID 与请求体重试原提交'
      return
    }
    handleWriteError(err)
  } finally {
    busy.value = ''
  }
}

async function queryWrite(key: string): Promise<void> {
  const write = pendingWrites.value.find((item) => item.key === key)
  if (!write) return
  const requestId = write.body.request_id as string
  const query = await queryAiReceipt(requestId)
  // A late receipt must never apply to a newer operation under the same key.
  const current = pendingWrites.value.find((item) => item.key === key)
  if (!current || (current.body.request_id as string) !== requestId) return
  if (query.state === 'found') {
    removePending(key)
    applyWrite(write, query.result)
    return
  }
  errorText.value = receiptMessage(query)
}

async function resubmitWrite(key: string): Promise<void> {
  const write = pendingWrites.value.find((item) => item.key === key)
  if (!write || guard() || busy.value) return
  busy.value = write.key
  errorText.value = ''
  try {
    await perform(write)
  } catch (err) {
    if (isIndeterminate(err)) {
      errorText.value = '重试仍未确认：请稍后再次查询提交结果'
      return
    }
    handleWriteError(err)
  } finally {
    busy.value = ''
  }
}

function handleWriteError(err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'PROMPT_VERSION_CONFLICT') {
      errorText.value = '指导已被其他操作更新：已重新读取，请比较后再保存'
      void loadPrompts()
      return
    }
    if (err.code === 'PROMPT_CONTRACT_CHANGED') {
      errorText.value = '指导契约已变化：请完成适配后再保存'
      void loadPrompts()
      return
    }
    errorText.value = err.message
    return
  }
  errorText.value = `操作失败：${String(err)}`
}

// --- AI config ---------------------------------------------------------------

async function saveConfig(): Promise<void> {
  if (guard() || busy.value || !config.value || !configLoaded.value) return
  if (!configForm.base_url.trim() || !configForm.model.trim()) {
    errorText.value = '请填写 API 前缀与模型标识'
    return
  }
  const key = 'config'
  if (hasPending(key)) {
    errorText.value = '存在未决配置提交：请先查询或重试原提交'
    return
  }
  const submittedBase = configForm.base_url
  const submittedModel = configForm.model
  const secretSubmitted = configForm.secret
  const body: Record<string, unknown> = {
    request_id: crypto.randomUUID(),
    expected_ai_config_version: config.value.ai_config_version,
    protocol_id: 'chat_completions_v1',
    base_url: submittedBase,
    model: submittedModel,
  }
  if (secretSubmitted !== '') body.secret = secretSubmitted
  await runWrite({
    key,
    label: 'AI 配置保存',
    method: 'PATCH',
    path: '/api/local/ai/config',
    body,
    kind: 'config',
    secretSubmitted,
    submittedBase,
    submittedModel,
  })
}

async function clearSecret(): Promise<void> {
  if (guard() || busy.value || !config.value || !configLoaded.value) return
  const key = 'clear'
  if (hasPending(key)) {
    errorText.value = '存在未决清除提交：请先查询或重试原提交'
    return
  }
  await runWrite({
    key,
    label: '清除密钥',
    method: 'POST',
    path: '/api/local/ai/config/clear-secret',
    body: {
      request_id: crypto.randomUUID(),
      expected_ai_config_version: config.value.ai_config_version,
    },
    kind: 'clear',
    secretSubmitted: configForm.secret,
  })
}

// --- prompts -----------------------------------------------------------------

function currentSubmitted(taskType: string): Record<string, string> {
  const prompt = promptFor(taskType)
  const live = promptGuides.value[taskType] ?? {}
  const map: Record<string, string> = {}
  for (const field of prompt?.fields ?? []) {
    map[field.key] = live[field.key] ?? field.default_text
  }
  return map
}

async function savePrompt(taskType: string): Promise<void> {
  const prompt = promptFor(taskType)
  if (!prompt || !promptsLoaded.value) return
  const key = `prompt-${taskType}`
  if (hasPending(key)) {
    errorText.value = '存在未决指导提交：请先查询或重试原提交'
    return
  }
  const submitted = currentSubmitted(taskType)
  await runWrite({
    key,
    label: `${taskTypeLabel(taskType)} 指导保存`,
    method: 'PATCH',
    path: `/api/local/ai/prompts/${pathSegment(taskType)}`,
    body: {
      request_id: crypto.randomUUID(),
      expected_personal_revision: prompt.personal_revision,
      contract_version: prompt.contract_version,
      guidance: submitted,
    },
    kind: 'prompt',
    taskType,
    mergedFields: Object.keys(submitted),
    beforeMap: submitted,
    success: `${taskTypeLabel(taskType)} 指导已保存`,
  })
}

async function viewDefault(taskType: string): Promise<void> {
  const prompt = promptFor(taskType)
  if (guard() || !prompt || busy.value) return
  busy.value = `default-${taskType}`
  errorText.value = ''
  try {
    const data = await apiGet<PromptDefault>(
      `/api/local/ai/prompts/${pathSegment(taskType)}/defaults/${prompt.required_contract_version}/${prompt.latest_default_revision}`,
    )
    defaults.value = { ...defaults.value, [taskType]: data }
    acceptFields.value = { ...acceptFields.value, [taskType]: [] }
  } catch (err) {
    handleWriteError(err)
  } finally {
    busy.value = ''
  }
}

function toggleAcceptField(taskType: string, key: string, checked: boolean): void {
  if (guard()) return
  const current = new Set(acceptFields.value[taskType] ?? [])
  if (checked) current.add(key)
  else current.delete(key)
  acceptFields.value = { ...acceptFields.value, [taskType]: [...current] }
}

async function acceptDefault(taskType: string): Promise<void> {
  const prompt = promptFor(taskType)
  const target = defaults.value[taskType]
  if (!prompt || !target) return
  const fields = acceptFields.value[taskType] ?? []
  if (fields.length === 0) {
    errorText.value = '请先勾选要接受默认文字的字段'
    return
  }
  const key = `accept-${taskType}`
  if (hasPending(key)) {
    errorText.value = '存在未决接受提交：请先查询或重试原提交'
    return
  }
  const before = currentSubmitted(taskType)
  await runWrite({
    key,
    label: `${taskTypeLabel(taskType)} 接受默认`,
    method: 'POST',
    path: `/api/local/ai/prompts/${pathSegment(taskType)}/accept-default`,
    body: {
      request_id: crypto.randomUUID(),
      expected_personal_revision: prompt.personal_revision,
      target_contract_version: target.contract_version,
      target_default_revision: target.default_revision,
      selected_fields: fields,
    },
    kind: 'accept',
    taskType,
    // Only the explicitly selected fields are merged (R08).
    mergedFields: [...fields],
    beforeMap: before,
    success: '已接受所选字段的默认文字（绑定实际查看的修订）',
  })
}

async function rejectDefault(taskType: string): Promise<void> {
  const prompt = promptFor(taskType)
  const target = defaults.value[taskType]
  if (!prompt || !target) return
  const key = `reject-${taskType}`
  if (hasPending(key)) {
    errorText.value = '存在未决拒绝提交：请先查询或重试原提交'
    return
  }
  await runWrite({
    key,
    label: `${taskTypeLabel(taskType)} 拒绝默认`,
    method: 'POST',
    path: `/api/local/ai/prompts/${pathSegment(taskType)}/reject-default`,
    body: {
      request_id: crypto.randomUUID(),
      expected_personal_revision: prompt.personal_revision,
      target_contract_version: target.contract_version,
      target_default_revision: target.default_revision,
    },
    kind: 'reject',
    taskType,
    // Reject changes only the rejected status: no guidance field is merged.
    mergedFields: [],
    beforeMap: currentSubmitted(taskType),
    success: '已记录拒绝该默认修订（不修改个人文字）',
  })
}

async function adaptPrompt(taskType: string): Promise<void> {
  const prompt = promptFor(taskType)
  if (!prompt || !promptsLoaded.value) return
  const key = `adapt-${taskType}`
  if (hasPending(key)) {
    errorText.value = '存在未决适配备提交：请先查询或重试原提交'
    return
  }
  const submitted = currentSubmitted(taskType)
  await runWrite({
    key,
    label: `${taskTypeLabel(taskType)} 适配新契约`,
    method: 'POST',
    path: `/api/local/ai/prompts/${pathSegment(taskType)}/adapt`,
    body: {
      request_id: crypto.randomUUID(),
      expected_personal_revision: prompt.personal_revision,
      target_contract_version: prompt.required_contract_version,
      target_default_revision: prompt.latest_default_revision,
      guidance: submitted,
    },
    kind: 'adapt',
    taskType,
    mergedFields: Object.keys(submitted),
    beforeMap: submitted,
    success: `${taskTypeLabel(taskType)} 已适配到当前必需契约版本`,
  })
}

function discardDrafts(): void {
  if (guard()) return
  promptGuides.value = JSON.parse(JSON.stringify(confirmedGuides.value))
  if (config.value) {
    configForm.base_url = config.value.base_url ?? ''
    configForm.model = config.value.model ?? ''
  }
  configForm.secret = ''
  errorText.value = ''
  messageText.value = ''
  defaults.value = {}
  acceptFields.value = {}
  ElMessage.info('已取消 AI 设置编辑')
}

const configStatusText = computed(() => {
  const current = config.value
  if (!current) return '正在读取配置…'
  if (!current.configured) return '尚未配置'
  if (!current.ready) return `已填写但不可用（${current.reason ?? '原因未知'}）`
  return '地址/模型/密钥已填写且密钥可解密（不代表已连通供应商）'
})

onMounted(() => {
  ;(window as unknown as { __d1AiSettings?: object }).__d1AiSettings = {
    config: () => config.value,
    configForm: () => ({ ...configForm }),
    configLoaded: () => configLoaded.value,
    promptsLoaded: () => promptsLoaded.value,
    configDirty: () => configDirty.value,
    promptsDirty: () => promptsDirty.value,
    draftActive: () => draftActive.value,
    draftTargets: () => draftTargets(),
    pendingWrites: () => pendingWrites.value.map((write) => ({ key: write.key, requestId: write.body.request_id })),
    errorText: () => errorText.value,
    messageText: () => messageText.value,
    prompts: () => prompts.value,
    promptPackage: () => promptPackage.value,
    promptPackageChecking: () => promptPackageChecking.value,
    checkPromptPackage: () => checkPromptPackage(),
    promptGuide: (taskType: string) => promptGuides.value[taskType] ?? {},
    confirmedGuide: (taskType: string) => confirmedGuides.value[taskType] ?? {},
    defaults: (taskType: string) => defaults.value[taskType] ?? null,
    setConfigDraft: (baseUrl: string, model: string, secret: string) => {
      if (guard() || !configLoaded.value) return
      configForm.base_url = baseUrl
      configForm.model = model
      configForm.secret = secret
    },
    setGuidance: (taskType: string, key: string, value: string) =>
      setGuidanceField(taskType, key, value),
    saveConfig: () => saveConfig(),
    clearSecret: () => clearSecret(),
    savePrompt: (taskType: string) => savePrompt(taskType),
    viewDefault: (taskType: string) => viewDefault(taskType),
    toggleAcceptField: (taskType: string, key: string, checked: boolean) =>
      toggleAcceptField(taskType, key, checked),
    acceptDefault: (taskType: string) => acceptDefault(taskType),
    rejectDefault: (taskType: string) => rejectDefault(taskType),
    adaptPrompt: (taskType: string) => adaptPrompt(taskType),
    queryWrite: (key: string) => queryWrite(key),
    resubmitWrite: (key: string) => resubmitWrite(key),
    discardDrafts: () => discardDrafts(),
    reload: () =>
      Promise.all([loadConfig(), loadPrompts(), loadPromptPackage()]),
  }
  void loadConfig()
  void loadPrompts()
  void loadPromptPackage()
})

onBeforeUnmount(() => {
  // The component is gone (leaving was only allowed when nothing was pending):
  // release the parent's draft flag and ignore a late prompt read.
  promptLoadSeq += 1
  emit('draft-active', false)
  delete (window as unknown as { __d1AiSettings?: object }).__d1AiSettings
})
const providerOpen = ref(false)
const promptsOpen = ref(false)
function onPartToggle(kind: 'provider' | 'prompts', event: Event): void {
  const target = event.target as HTMLDetailsElement | null
  if (!target) return
  if (kind === 'provider') providerOpen.value = target.open
  else promptsOpen.value = target.open
}
async function openPart(kind: string): Promise<void> {
  if (kind === 'ai-prompts') promptsOpen.value = true
  else providerOpen.value = true
  await nextTick()
}
/** Prefer the matching unresolved receipt, then the region/control itself. */
async function focusDraftTarget(kind: string): Promise<void> {
  await openPart(kind)
  const prefixes = kind === 'ai-prompts'
    ? ['prompt-', 'default-', 'accept-', 'reject-', 'adapt-']
    : ['config', 'clear']
  const receipt = Array.from(
    document.querySelectorAll('[data-d1="ai-pending-write"]'),
  ).find((card) => {
    const key = card.getAttribute('data-ai-write-key') ?? ''
    return prefixes.some((prefix) =>
      prefix.endsWith('-') ? key.startsWith(prefix) : key === prefix,
    )
  })
  const selector =
    kind === 'ai-prompts' ? '[data-d1="ai-prompts"]' : '[data-d1="ai-base-url"]'
  const element =
    (receipt as HTMLElement | undefined) ??
    (document.querySelector(selector) as HTMLElement | null)
  if (!element) return
  element.scrollIntoView?.({ block: 'center' })
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus?.()
}
/** Open the prompt group and locate one registered task's guidance block. */
async function focusPromptTask(taskType: string): Promise<void> {
  promptsOpen.value = true
  await nextTick()
  const element = document.querySelector(
    `[data-d1="prompt-${taskType}"]`,
  ) as HTMLElement | null
  if (!element) return
  element.scrollIntoView?.({ block: 'center' })
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus?.()
}

defineExpose({ draftTargets, focusDraftTarget, focusPromptTask })
</script>

<template>
  <details
    class="settings-group settings-part"
    data-d1="settings-group-ai-provider"
    :open="providerOpen"
    @toggle="onPartToggle('provider', $event)"
  >
    <summary>AI 供应商 <span class="muted">地址、模型、密钥</span></summary>
  <el-card class="section" shadow="never" data-d1="ai-settings">
    <template #header>AI 配置（地址 / 模型 / 密钥）</template>
    <p class="muted">
      保存与读取只做本机格式与加密校验，不会试调用供应商；密钥仅保存期间留存，成功后清空输入框。
    </p>
    <el-alert v-if="config" type="info" :closable="false" class="section" :title="configStatusText" />
    <div class="fields">
      <div class="field wide">
        <label>API 前缀（HTTPS，可含 /v1）</label>
        <el-input v-model="configForm.base_url" placeholder="https://example.com/v1" maxlength="2048" :disabled="frozen || !configLoaded" data-d1="ai-base-url" />
      </div>
      <div class="field">
        <label>模型标识</label>
        <el-input v-model="configForm.model" placeholder="供应商模型标识" maxlength="200" :disabled="frozen || !configLoaded" data-d1="ai-model" />
      </div>
      <div class="field">
        <label>API 密钥（留空表示保留现有）</label>
        <el-input v-model="configForm.secret" type="password" show-password placeholder="仅在保存时使用" :disabled="frozen || !configLoaded" data-d1="ai-secret" />
      </div>
    </div>
    <div class="row">
      <el-button type="primary" :loading="busy === 'config'" :disabled="frozen || !configLoaded || hasPending('config')" data-d1="ai-save-config" @click="saveConfig">保存配置</el-button>
      <el-button :loading="busy === 'clear'" :disabled="frozen || !configLoaded || hasPending('clear')" data-d1="ai-clear-secret" @click="clearSecret">清除密钥</el-button>
      <el-button :disabled="frozen" data-d1="ai-discard-settings" @click="discardDrafts">取消编辑（还原）</el-button>
      <span class="muted" v-if="config">
        配置版本 v{{ config.ai_config_version }} · 密钥已保存：{{ config.has_secret ? '是' : '否' }}
      </span>
    </div>
    <el-card v-for="write in pendingWrites" :key="write.key" shadow="never" class="pending-card" data-d1="ai-pending-write" :data-ai-write-key="write.key">
      <span class="muted">未决写入：{{ write.label }}（请求 {{ String(write.body.request_id).slice(0, 8) }}…）</span>
      <div class="row">
        <el-button size="small" type="warning" @click="queryWrite(write.key)">查询提交结果</el-button>
        <el-button size="small" type="danger" @click="resubmitWrite(write.key)">重试原提交（同一请求）</el-button>
      </div>
    </el-card>
  </el-card>

  </details>
  <details
    class="settings-group settings-part"
    data-d1="settings-group-ai-prompts"
    :open="promptsOpen"
    @toggle="onPartToggle('prompts', $event)"
  >
    <summary>提示词 <span class="muted">默认指导、个人修改与功能包</span></summary>
  <el-card class="section" shadow="never" data-d1="ai-prompt-package">
    <template #header>提示词功能包（默认指导）</template>
    <p class="muted">
      只更新程序已登记任务的默认指导文字；输入输出结构、周计划栏目、图片、模型、预算和权限仍由程序固定。
      有个人修改的字段沿用个人文字；已开始的任务继续使用开始时的版本。
    </p>
    <div class="row" data-d1="ai-prompt-package-status">
      <el-tag size="small" :type="promptPackage?.configured ? 'success' : 'info'">
        {{ promptPackageStateLabel() }}
      </el-tag>
      <span class="muted">{{ promptPackageVersionText() }}</span>
      <span v-if="promptPackage?.published_at" class="muted">
        发布于 {{ promptPackage.published_at }}
      </span>
      <span v-if="promptPackage?.last_checked_at" class="muted">
        最近检查 {{ promptPackage.last_checked_at }}
      </span>
    </div>
    <p v-if="promptPackage?.notes" class="muted" data-d1="ai-prompt-package-notes">
      变更说明：{{ promptPackage.notes }}
    </p>
    <p class="muted" data-d1="ai-prompt-package-message">
      {{ promptPackage?.message ?? '正在读取提示词功能包状态…' }}
    </p>
    <p v-if="promptPackage && !promptPackage.configured" class="muted">
      当前源码未配置正式发布来源；检查操作不会发起网络请求，继续使用内置或已验证文字。
    </p>
    <p v-else-if="promptPackage?.package_tasks.length" class="muted">
      本包快照 {{ promptPackage.package_tasks.length }} 项，其中
      {{ promptPackage.allowed_tasks.length }} 项有可更新文字。
    </p>
    <div class="row">
      <el-button
        type="primary"
        size="small"
        data-d1="ai-prompt-package-check"
        :loading="promptPackageChecking"
        :disabled="frozen || promptPackageChecking"
        @click="checkPromptPackage"
      >
        检查提示词更新
      </el-button>
    </div>
  </el-card>

  <el-card class="section" shadow="never" data-d1="ai-prompts">
    <template #header>已登记任务指导（按模块分组，默认文字 / 个人修改）</template>
    <p class="muted">指导只在任务开始时取当时有效版本；接受默认只覆盖所选字段并绑定实际查看的修订。</p>
        <div
      v-for="group in promptGroups"
      :key="group.key"
      class="prompt-group"
      :data-d1="`prompt-group-${group.key}`"
    >
      <h4 class="prompt-group-title">{{ group.label }}</h4>
      <div
        v-for="prompt in group.items"
        :key="prompt.task_type"
        class="prompt-block"
        :data-d1="`prompt-${prompt.task_type}`"
      >
        <div class="prompt-head">
          <strong>{{ taskTypeLabel(prompt.task_type) }}</strong>
          <el-tag v-if="prompt.adaptation_required" size="small" type="warning">需要适配新契约</el-tag>
          <span class="muted">
            个人修订 r{{ prompt.personal_revision }} · 契约 v{{ prompt.contract_version }}
            · 必需契约 v{{ prompt.required_contract_version }}
            · 最新默认 r{{ prompt.latest_default_revision }}
          </span>
        </div>
        <p v-if="prompt.rejected_default_revision" class="muted">
          已拒绝默认修订 r{{ prompt.rejected_default_revision }}（个人文字未改动）
        </p>
        <div v-for="field in prompt.fields" :key="field.key" class="field">
          <label>{{ displayFieldLabel(field) }}</label>
          <el-input
            type="textarea"
            :rows="2"
            :disabled="frozen || !promptsLoaded"
            :model-value="(promptGuides[prompt.task_type] ?? {})[field.key] ?? field.default_text"
            @update:model-value="(value: string) => setGuidanceField(prompt.task_type, field.key, value)"
          />
        </div>
        <div v-if="Object.keys(prompt.orphaned_guidance).length" class="orphan">
          <span class="muted">已移出当前契约、不再发送给模型的个人字段：</span>
          <span v-for="(value, key) in prompt.orphaned_guidance" :key="key" class="orphan-item">{{ key }}（{{ value }}）</span>
        </div>
        <div class="row">
          <el-button size="small" :disabled="frozen || !promptsLoaded || hasPending(`prompt-${prompt.task_type}`)" :loading="busy === `prompt-${prompt.task_type}`" @click="savePrompt(prompt.task_type)">保存指导</el-button>
          <el-button size="small" :disabled="frozen || !promptsLoaded" :loading="busy === `default-${prompt.task_type}`" @click="viewDefault(prompt.task_type)">查看最新默认</el-button>
          <el-button
            v-if="prompt.adaptation_required"
            size="small"
            type="warning"
            :disabled="frozen || !promptsLoaded || hasPending(`adapt-${prompt.task_type}`)"
            :loading="busy === `adapt-${prompt.task_type}`"
            @click="adaptPrompt(prompt.task_type)"
          >
            适配新契约
          </el-button>
        </div>
        <div v-if="defaults[prompt.task_type]" class="default-block" :data-d1="`default-${prompt.task_type}`">
          <h4>默认修订 r{{ defaults[prompt.task_type]?.default_revision }}（契约 v{{ defaults[prompt.task_type]?.contract_version }}）</h4>
          <div v-for="field in defaults[prompt.task_type]?.fields ?? []" :key="field.key" class="default-field">
            <el-checkbox
              :model-value="(acceptFields[prompt.task_type] ?? []).includes(field.key)"
              :disabled="frozen"
              @update:model-value="(checked: boolean) => toggleAcceptField(prompt.task_type, field.key, checked)"
            >
              {{ displayFieldLabel(field) }}
            </el-checkbox>
            <pre class="block">{{ defaults[prompt.task_type]?.guidance[field.key] || '（空）' }}</pre>
          </div>
          <div class="row">
            <el-button size="small" type="primary" :disabled="frozen || hasPending(`accept-${prompt.task_type}`)" :loading="busy === `accept-${prompt.task_type}`" @click="acceptDefault(prompt.task_type)">接受所选默认</el-button>
            <el-button size="small" :disabled="frozen || hasPending(`reject-${prompt.task_type}`)" :loading="busy === `reject-${prompt.task_type}`" @click="rejectDefault(prompt.task_type)">拒绝该默认修订</el-button>
          </div>
        </div>
      </div>
    </div>

  </el-card>

  </details>
  <el-alert v-if="errorText" type="error" :closable="false" class="section" data-d1="ai-settings-error" :title="errorText" />
  <el-alert v-if="messageText" type="success" :closable="false" class="section" data-d1="ai-settings-message" :title="messageText" />
</template>

<style scoped>
.section {
  margin-top: 16px;
}
.settings-part {
  margin-top: 16px;
  border: 1px solid var(--kgm-border);
  border-radius: 6px;
  padding: 0 14px 14px;
}
.settings-part > summary {
  cursor: pointer;
  padding: 12px 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--kgm-text);
}
.fields {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: flex-end;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
}
.field.wide {
  min-width: 320px;
}
.field label {
  font-size: 0.85rem;
  color: var(--kgm-text);
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.prompt-group {
  margin-top: 18px;
}
.prompt-group-title {
  margin: 0 0 4px;
  font-size: 1rem;
  color: var(--kgm-text);
}
.prompt-block {
  border-top: 1px dashed var(--kgm-border);
  padding-top: 10px;
  margin-top: 10px;
}
.prompt-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.orphan {
  margin-top: 8px;
}
.orphan-item {
  margin-right: 10px;
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
.default-block {
  background: var(--kgm-bg);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  padding: 10px;
  margin-top: 10px;
}
.pending-card {
  margin-top: 10px;
  background: color-mix(in srgb, var(--kgm-warning) 12%, var(--kgm-surface));
}
.block {
  margin: 4px 0 0;
  padding: 6px 8px;
  background: var(--kgm-surface);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.8rem;
  max-height: 160px;
  overflow: auto;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
</style>
