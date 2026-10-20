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
import { isIndeterminate } from '../operations'
import type { ClassGames, ConfigPreview, GameLocation } from '../types'

const props = defineProps<{ frozen?: boolean }>()

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
let inputSeq = 0

function snapshot(): GameSnapshot {
  return {
    locations: locations.value.map((location) => ({ ...location })),
    game_scope: gameScope.value,
    guidance: guidance.value,
  }
}

const draftActive = computed(
  () =>
    JSON.stringify(snapshot()) !== JSON.stringify(confirmed.value) ||
    preview.value !== null ||
    previewing.value ||
    applying.value ||
    pendingApply.value !== null,
)
// The watcher is the single source of truth for the parent's draft state (no
// manual emit can leave a stale ``true`` after the pending apply clears).
watch(draftActive, (value) => emit('draft-active', value), { immediate: true })

/** Inputs are disabled while frozen/loading/unresolved/in-flight. */
function inputsBlocked(): boolean {
  return props.frozen === true || !loaded.value || pendingApply.value !== null
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

function cancelDraft(): void {
  if (props.frozen || applying.value || pendingApply.value) {
    if (pendingApply.value) errorText.value = '应用结果待核对：不能取消丢弃，请先查询提交结果'
    return
  }
  locations.value = current.value ? current.value.change.locations.map((l) => ({ ...l })) : []
  gameScope.value = current.value?.change.game_scope ?? ''
  guidance.value = current.value?.change.guidance ?? ''
  preview.value = null
  errorText.value = ''
  messageText.value = ''
  inputSeq += 1
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
  }
  void load()
})

onBeforeUnmount(() => {
  emit('draft-active', false)
  delete (window as unknown as { __d1GameConfig?: object }).__d1GameConfig
})
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
    <div v-for="(location, index) in locations" :key="index" class="location-row" data-d1="game-location">
      <el-select v-model="location.kind" size="small" class="kind-select" :disabled="frozen || !loaded || !!pendingApply" @change="invalidate">
        <el-option label="区域" value="area" />
        <el-option label="专用室" value="special_room" />
        <el-option label="户外场地" value="outdoor" />
      </el-select>
      <el-input v-model="location.name" size="small" placeholder="地点名称（1–80 字）" maxlength="80" class="name-input" :disabled="frozen || !loaded || !!pendingApply" @input="invalidate" />
      <el-input v-model="location.guidance" size="small" placeholder="该地点的简短限制/指导（可空）" maxlength="2000" class="guide-input" :disabled="frozen || !loaded || !!pendingApply" @input="invalidate" />
      <el-button size="small" text type="danger" :disabled="frozen || !loaded || !!pendingApply" @click="removeLocation(index)">移除</el-button>
    </div>
    <el-button size="small" data-d1="game-add-location" :disabled="frozen || !loaded || !!pendingApply" @click="addLocation">添加地点</el-button>
    <div class="field"><label>游戏范围（可空）</label><el-input v-model="gameScope" type="textarea" :rows="2" maxlength="8000" :disabled="frozen || !loaded || !!pendingApply" @input="invalidate" /></div>
    <div class="field"><label>通用限制 / 指导（可空）</label><el-input v-model="guidance" type="textarea" :rows="2" maxlength="8000" :disabled="frozen || !loaded || !!pendingApply" @input="invalidate" /></div>
    <div class="row">
      <el-button size="small" data-d1="game-preview" :loading="previewing" :disabled="frozen || !loaded || !!pendingApply" @click="previewChange">预览修改</el-button>
      <el-button
        size="small"
        type="primary"
        data-d1="game-apply"
        :loading="applying"
        :disabled="frozen || !loaded || !!pendingApply || !preview || !preview.changed"
        @click="applyPreview"
      >
        确认应用
      </el-button>
      <el-button size="small" data-d1="game-cancel" :disabled="frozen || !!pendingApply" @click="cancelDraft">取消编辑</el-button>
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
  color: #606266;
}
.row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.pending-block {
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 4px;
  padding: 8px 10px;
  margin-top: 10px;
}
.preview-block {
  margin-top: 12px;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
</style>
