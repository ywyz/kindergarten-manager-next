<script setup lang="ts">
/**
 * One-to-one listening editor (L2).
 *
 * The five domain tabs share one record revision and one child name. Every
 * save is a partial patch built against the last confirmed baseline; late
 * responses never overwrite newer input. The template rows come from the
 * record-bound template response (record grade + stored version/hash), never
 * from the current class grade.
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { ElMessage } from 'element-plus'
import type { LocalContext } from '../types'
import type { LeaveEditor } from '../leave'
import { PhotoUrlCache } from '../observation-photos'
import ListeningExportDialog from '../components/ListeningExportDialog.vue'
import ListeningAiPanel from '../components/ListeningAiPanel.vue'
import {
  DOMAIN_LABELS,
  GRADE_LABELS,
  LISTENING_DOMAINS,
  ListeningSession,
  createListeningState,
  formatRecordTime,
  listeningApi,
  newRequestId,
  type ListeningDomain,
  type SaveOutcome,
} from '../listening'

const props = defineProps<{
  context: LocalContext
  recordId: string
  frozen?: boolean
  disabled?: boolean
  profileEpoch?: number
}>()

const emit = defineEmits<{
  (e: 'register-editor', owner: string | null, bridge: LeaveEditor | null): void
  (e: 'busy', payload: { owner: string; busy: boolean }): void
  (e: 'back'): void
  (e: 'open-settings'): void
}>()

const instanceId = newRequestId()
const state = reactive(createListeningState(props.recordId))
const session = new ListeningSession(listeningApi, state)
const currentOwner = ref(
  `listening:${props.recordId}:${props.profileEpoch ?? 0}:${instanceId}`,
)
const canEdit = computed(() => !props.frozen && !props.disabled)
const composing = ref(false)
let compositionWaiters: Array<() => void> = []
let actionGeneration = 0
const actionCount = ref(0)
let actionChain: Promise<unknown> = Promise.resolve()
const aiBusy = ref(false)
const aiDraft = ref(false)
const actionBusy = computed(
  () => actionCount.value > 0 || state.busy || state.savePromise !== null,
)
// AI phases are part of the same navigation barrier as saves/exports: a
// domain switch or leave must not reset the panel while its create/adopt
// request is in flight.  ensureAiSaved stays outside this check, so the
// panel's internal save cannot deadlock against its own busy flag.
const canMutate = computed(
  () => canEdit.value && !actionBusy.value && !aiBusy.value,
)
const exportOpen = ref(false)
const exportTermId = ref('')
const exportBusy = ref(false)
const form = computed(() => session.form())
const template = computed(() => session.template())
const record = computed(() => state.record)
const termName = computed(() => {
  const termId = record.value?.term_id
  return props.context.terms.find((term) => term.id === termId)?.name ?? termId ?? ''
})
const gradeLabel = computed(
  () => GRADE_LABELS[record.value?.grade ?? ''] ?? record.value?.grade ?? '',
)

const photoUrls = reactive<Record<string, string>>({})
const photoErrors = reactive<Record<string, string>>({})
const photoLoading = reactive<Record<string, boolean>>({})
let photoGeneration = 0
const photoCache = new PhotoUrlCache({
  load: (assetId, signal) => session.loadAsset(assetId, signal),
  max: 32,
  maxPending: 4,
})

function clearPhotoUrls(): void {
  for (const assetId of Object.keys(photoUrls)) delete photoUrls[assetId]
  for (const assetId of Object.keys(photoErrors)) delete photoErrors[assetId]
  for (const assetId of Object.keys(photoLoading)) delete photoLoading[assetId]
}

async function ensurePhoto(assetId: string, explicit = false): Promise<void> {
  const generation = photoGeneration
  const domain = state.domain
  const stillCurrent = () =>
    generation === photoGeneration &&
    state.domain === domain &&
    (session.form()?.groups ?? []).some(
      (group) => group.asset_id === assetId,
    )
  photoLoading[assetId] = true
  delete photoErrors[assetId]
  try {
    const url = await photoCache.ensure(assetId)
    if (!stillCurrent()) return
    if (url) photoUrls[assetId] = url
    else if (explicit) photoErrors[assetId] = '图片读取未返回内容，可重试'
  } catch (error) {
    if (!stillCurrent()) return
    const message = error instanceof Error ? error.message : String(error)
    photoErrors[assetId] = message.includes('404')
      ? '图片读取失败（404），可重试'
      : '图片读取失败，可重试'
  } finally {
    // A stale generation must write nothing: invalidate/remove already
    // cleared its map, and a newer request for the same asset may own
    // photoLoading/photoErrors/photoUrls now.
    if (stillCurrent()) photoLoading[assetId] = false
  }
}

function retryPhoto(assetId: string): void {
  void ensurePhoto(assetId, true)
}

function syncPhotoUrls(): void {
  const groups = session.form()?.groups ?? []
  const current = new Set(
    groups.map((group) => group.asset_id).filter((id): id is string => Boolean(id)),
  )
  for (const assetId of Object.keys(photoUrls)) {
    if (!current.has(assetId)) {
      photoCache.release(assetId)
      delete photoUrls[assetId]
    }
  }
  for (const assetId of Object.keys(photoErrors)) {
    if (!current.has(assetId)) delete photoErrors[assetId]
  }
  for (const assetId of Object.keys(photoLoading)) {
    if (!current.has(assetId)) delete photoLoading[assetId]
  }
  for (const assetId of current) void ensurePhoto(assetId)
}

function invalidatePhotos(): void {
  photoGeneration += 1
  photoCache.invalidate()
  clearPhotoUrls()
  syncPhotoUrls()
}

watch(
  () => [state.recordId, state.domain, props.profileEpoch ?? 0],
  () => invalidatePhotos(),
)
watch(
  () => (session.form()?.groups ?? []).map((group) => group.asset_id).join('|'),
  () => syncPhotoUrls(),
)

function releaseComposition(): void {
  composing.value = false
  const waiters = compositionWaiters.splice(0)
  for (const resolve of waiters) resolve()
}

async function settleComposition(): Promise<void> {
  if (composing.value) {
    await new Promise<void>((resolve) => {
      compositionWaiters.push(resolve)
    })
  }
  await nextTick()
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
}

function onCompositionStart(): void {
  composing.value = true
}

function onCompositionEnd(): void {
  composing.value = false
  void nextTick().then(() => {
    const waiters = compositionWaiters.splice(0)
    for (const resolve of waiters) resolve()
  })
}

function runExclusive<T>(work: () => Promise<T>): Promise<T> {
  const next = actionChain.then(work, work)
  actionChain = next.catch(() => undefined)
  return next
}

async function runMutating<T>(
  work: () => Promise<T>,
): Promise<T | undefined> {
  const generation = actionGeneration
  await settleComposition()
  if (generation !== actionGeneration) return undefined
  actionCount.value += 1
  try {
    return await runExclusive(async () => {
      if (generation !== actionGeneration) return undefined
      return work()
    })
  } finally {
    if (generation === actionGeneration) {
      actionCount.value = Math.max(0, actionCount.value - 1)
    }
  }
}

const bridge: LeaveEditor = {
  isDirty: () => session.isDirty() || aiDraft.value,
  identity: () => session.identity(),
  settle: settleComposition,
  saveCurrent: () => runExclusive(() => session.saveCurrent()),
  blockingDraft: () =>
    state.unknown
      ? {
          kind: 'listening',
          message: state.error || '倾听保存结果待核对：请先处理原请求',
        }
      : aiDraft.value
        ? {
            kind: 'listening',
            message: 'AI 候选尚未确认或采用：请先采用/取消候选再离开',
          }
        : null,
}

function register(): void {
  emit('register-editor', currentOwner.value, bridge)
}

function unregister(owner = currentOwner.value): void {
  emit('register-editor', owner, null)
  emit('busy', { owner, busy: false })
}

function emitBusy(): void {
  emit('busy', {
    owner: currentOwner.value,
    busy:
      aiBusy.value ||
      exportBusy.value ||
      state.busy ||
      state.savePromise !== null,
  })
}

watch(actionBusy, emitBusy)
watch(exportBusy, emitBusy)
watch(aiBusy, emitBusy)

function handleAiBusy(value: boolean): void {
  aiBusy.value = value
}

function handleAiDraft(value: boolean): void {
  aiDraft.value = value
}

async function ensureAiSaved(): Promise<number | null> {
  if (!canEdit.value || state.unknown) return null
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return null
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning(outcomeMessage(outcome))
    return null
  }
  if (session.isDirty()) {
    ElMessage.warning('保存期间又有新输入；请再次保存后再创建 AI 任务')
    syncPhotoUrls()
    return null
  }
  return state.revision >= 1 ? state.revision : null
}

async function handleAiAdopted(payload: {
  domain: ListeningDomain
  revision: number
  patch: Record<string, unknown>
}): Promise<void> {
  session.applyConfirmedAdoption(payload.domain, payload.revision, payload.patch)
  syncPhotoUrls()
  emitBusy()
}

function handleExportBusy(value: boolean): void {
  exportBusy.value = value
}

async function load(): Promise<void> {
  const ok = await session.load()
  if (!ok) {
    ElMessage.error(state.error || '倾听记录读取失败')
    return
  }
  syncPhotoUrls()
}

function outcomeMessage(outcome: SaveOutcome): string {
  if (outcome === 'conflict') return state.error || '内容版本冲突，未覆盖当前输入'
  if (outcome === 'indeterminate') return state.error || '保存结果未知，请核对原请求'
  if (outcome === 'failed') return state.error || '保存失败，已保留输入'
  return ''
}

async function manualSave(): Promise<void> {
  if (!canEdit.value) return
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    syncPhotoUrls()
    if (session.isDirty()) {
      ElMessage.warning('已保存已确认部分；保存期间的新输入仍保留，请再次保存')
    } else {
      ElMessage.success(outcome === 'saved' ? '已保存' : '没有需要保存的修改')
    }
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function openExport(): Promise<void> {
  if (!canMutate.value) return
  if (state.unknown) {
    ElMessage.warning('保存结果待核对：请先处理原请求，不能导出一份未确认的内容')
    return
  }
  // Export only after the current draft is confirmed saved.  A failed or
  // indeterminate save keeps the editor page and produces no Word.
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning(outcomeMessage(outcome))
    return
  }
  if (session.isDirty()) {
    ElMessage.warning('保存期间又有新输入，已留在编辑页；请再次保存后再合册')
    syncPhotoUrls()
    return
  }
  const termId = record.value?.term_id ?? ''
  if (!termId) {
    ElMessage.warning('记录缺少学期归属，暂不能合册')
    return
  }
  exportTermId.value = termId
  exportOpen.value = true
}

async function selectDomain(domain: ListeningDomain): Promise<void> {
  if (!canMutate.value || domain === state.domain) return
  const outcome = await runMutating(() => session.setDomain(domain))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

function setField(
  field:
    | 'observation_date'
    | 'adult_count'
    | 'child_age'
    | 'goal'
    | 'observation_area'
    | 'overall_evaluation'
    | 'support_strategy',
  value: string,
): void {
  session.setField(field, value)
}

function setGroupField(
  groupId: string,
  field: 'work_date' | 'listening_text',
  value: string,
): void {
  session.setGroupField(groupId, field, value)
}

function starsFor(itemId: string): number | null {
  return (
    session
      .form()
      ?.evaluation.find((item) => item.item_id === itemId)?.stars ?? null
  )
}

function setStars(itemId: string, stars: number | null): void {
  if (!canEdit.value) return
  session.setStars(itemId, stars)
}

function moveGroup(groupId: string, direction: -1 | 1): void {
  if (!canEdit.value) return
  session.moveGroup(groupId, direction)
}

async function pickPhoto(event: Event, groupId: string): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files && input.files.length > 0 ? input.files[0] : null
  input.value = ''
  // Cancelled/empty selection: return before any save or upload request.
  if (!file || !canEdit.value) return
  const outcome = await runMutating(() => session.importPhoto(groupId, file))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('照片已保存')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function removePhoto(groupId: string): Promise<void> {
  if (!canEdit.value) return
  const outcome = await runMutating(() => session.removePhoto(groupId))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('照片已移除，日期和正文保留')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function retryUnknown(): Promise<void> {
  if (!canEdit.value) return
  const outcome = await runMutating(() => session.retryUnknown())
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('原请求已确认并保存')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function checkReceipt(): Promise<void> {
  if (!canEdit.value) return
  const found = await runMutating(() => session.checkUnknownReceipt())
  if (found === undefined) return
  ElMessage[found ? 'success' : 'warning'](state.error)
}

function resetForContext(): void {
  actionGeneration += 1
  actionCount.value = 0
  exportOpen.value = false
  exportBusy.value = false
  aiBusy.value = false
  aiDraft.value = false
  releaseComposition()
  invalidatePhotos()
  session.reset()
  const previous = currentOwner.value
  currentOwner.value = `listening:${props.recordId}:${props.profileEpoch ?? 0}:${instanceId}`
  if (previous !== currentOwner.value) {
    unregister(previous)
    register()
  }
  void load()
}

watch(
  () => props.profileEpoch ?? 0,
  () => resetForContext(),
)

onMounted(() => {
  register()
  emitBusy()
  void load()
})

onBeforeUnmount(() => {
  actionGeneration += 1
  actionCount.value = 0
  photoGeneration += 1
  releaseComposition()
  unregister()
  photoCache.dispose()
  clearPhotoUrls()
  session.reset()
})

defineExpose({
  resetForContext,
  saveCurrent: () => runExclusive(() => session.saveCurrent()),
})
</script>

<template>
  <div class="listening-editor" @compositionstart="onCompositionStart" @compositionend="onCompositionEnd">
    <div class="topbar">
      <div class="identity">
        <el-button
          data-d1="listening-editor-back"
          :disabled="!canMutate"
          @click="emit('back')"
        >
          返回列表
        </el-button>
        <el-button
          data-d1="listening-editor-settings"
          :disabled="!canMutate"
          @click="emit('open-settings')"
        >
          设置与配置维护
        </el-button>
        <div>
          <h2>{{ state.name || '倾听记录' }}</h2>
          <p class="muted">
            班级 {{ props.context.class?.name || '' }} ·
            记录年级 {{ gradeLabel }} ·
            学期 {{ termName }} ·
            创建 {{ formatRecordTime(record?.created_at || '') }} ·
            标识 {{ state.recordId.slice(0, 8) }}
          </p>
        </div>
      </div>
      <div class="actions">
        <el-button
          data-d1="listening-editor-export"
          :disabled="!canMutate || state.unknown"
          @click="openExport"
        >
          按幼儿合册
        </el-button>
        <el-button
          type="primary"
          data-d1="listening-editor-save"
          :loading="actionBusy"
          :disabled="!canMutate"
          @click="manualSave"
        >
          保存
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="state.unknown"
      type="warning"
      :closable="false"
      :title="state.error"
      class="block"
      data-d1="listening-unknown"
    >
      <el-button
        size="small"
        data-d1="listening-retry-original"
        :disabled="!canMutate"
        @click="retryUnknown"
      >
        重试原请求
      </el-button>
      <el-button
        size="small"
        data-d1="listening-check-receipt"
        :disabled="!canMutate"
        @click="checkReceipt"
      >
        核对回执
      </el-button>
    </el-alert>
    <el-alert
      v-else-if="state.error"
      type="error"
      :closable="false"
      :title="state.error"
      class="block"
    />
    <el-alert
      v-if="state.loaded && state.name !== state.nameBaseline"
      type="info"
      :closable="false"
      title="姓名修改尚未保存；保存后会同步到同一记录的五张领域表。"
      class="block"
    />

    <el-card shadow="never" class="block">
      <div class="shared-name">
        <span class="muted">幼儿姓名</span>
        <el-input
          :model-value="state.name"
          maxlength="80"
          show-word-limit
          data-d1="listening-name"
          :disabled="!canEdit"
          @update:model-value="session.setName(String($event))"
        />
        <span class="muted">五表共用此姓名；改名仍是同一条记录。</span>
      </div>
    </el-card>

    <div v-if="!state.loaded" v-loading="state.busy" class="block loading-block">
      正在读取倾听记录...
    </div>
    <template v-else>
      <div class="domain-tabs">
        <el-button
          v-for="domain in LISTENING_DOMAINS"
          :key="domain"
          :type="state.domain === domain ? 'primary' : 'default'"
          :data-d1="`listening-domain-${domain}`"
          :disabled="!canMutate"
          @click="selectDomain(domain)"
        >
          {{ DOMAIN_LABELS[domain] }}
        </el-button>
      </div>

      <el-card v-if="form && template" shadow="never" class="block">
        <h3>{{ template.domain_label }}领域 · {{ template.grade_label }} · {{ template.version }}</h3>
        <p class="muted">模板散列 {{ template.sha256.slice(0, 12) }}… · 评价原文来自本记录绑定版本。</p>

        <div class="header-grid">
          <label>
            <span>观察日期/时段</span>
            <el-input
              :model-value="form.observation_date ?? ''"
              data-d1="listening-observation-date"
              :disabled="!canEdit"
              @update:model-value="setField('observation_date', String($event))"
            />
          </label>
          <label>
            <span>成人数目</span>
            <el-input
              :model-value="form.adult_count ?? ''"
              data-d1="listening-adult-count"
              :disabled="!canEdit"
              @update:model-value="setField('adult_count', String($event))"
            />
          </label>
          <label>
            <span>幼儿年龄</span>
            <el-input
              :model-value="form.child_age ?? ''"
              data-d1="listening-child-age"
              :disabled="!canEdit"
              @update:model-value="setField('child_age', String($event))"
            />
          </label>
          <label class="wide">
            <span>目标</span>
            <el-input
              :model-value="form.goal ?? ''"
              type="textarea"
              :rows="2"
              data-d1="listening-goal"
              :disabled="!canEdit"
              @update:model-value="setField('goal', String($event))"
            />
          </label>
          <label>
            <span>观察区域</span>
            <el-input
              :model-value="form.observation_area ?? ''"
              data-d1="listening-observation-area"
              :disabled="!canEdit"
              @update:model-value="setField('observation_area', String($event))"
            />
          </label>
        </div>

        <div class="groups">
          <el-card
            v-for="(group, index) in form.groups"
            :key="group.group_id"
            shadow="never"
            class="group-card"
          >
            <div class="group-head">
              <strong>第 {{ index + 1 }} 组</strong>
              <span class="muted">稳定标识 {{ group.group_id.slice(0, 8) }}</span>
              <div class="group-actions">
                <el-button
                  size="small"
                  :disabled="!canEdit || index === 0"
                  data-d1="listening-group-up"
                  @click="moveGroup(group.group_id, -1)"
                >
                  上移
                </el-button>
                <el-button
                  size="small"
                  :disabled="!canEdit || index === form.groups.length - 1"
                  data-d1="listening-group-down"
                  @click="moveGroup(group.group_id, 1)"
                >
                  下移
                </el-button>
              </div>
            </div>
            <div class="group-grid">
              <div class="photo-cell">
                <div class="photo-preview">
                  <img
                    v-if="group.asset_id && photoUrls[group.asset_id]"
                    :src="photoUrls[group.asset_id]"
                    alt="幼儿绘画照片"
                  />
                  <span
                    v-else-if="group.asset_id && photoErrors[group.asset_id]"
                    class="photo-error"
                  >
                    {{ photoErrors[group.asset_id] }}
                    <el-button
                      size="small"
                      text
                      :disabled="!canEdit || photoLoading[group.asset_id]"
                      data-d1="listening-photo-retry"
                      @click="retryPhoto(group.asset_id)"
                    >
                      重试读取
                    </el-button>
                  </span>
                  <span v-else class="muted">
                    {{ group.asset_id ? '图片读取中…' : '尚未选择照片' }}
                  </span>
                </div>
                <label class="file-label" :class="{ disabled: !canMutate }">
                  {{ group.asset_id ? '替换照片' : '选择照片' }}
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif,image/bmp"
                    :disabled="!canMutate"
                    data-d1="listening-photo-input"
                    @change="pickPhoto($event, group.group_id)"
                  />
                </label>
                <el-button
                  v-if="group.asset_id"
                  size="small"
                  type="danger"
                  text
                  :disabled="!canMutate"
                  data-d1="listening-photo-remove"
                  @click="removePhoto(group.group_id)"
                >
                  移除图片
                </el-button>
              </div>
              <div class="text-cell">
                <label>
                  <span>作品日期（可范围文本）</span>
                  <el-input
                    :model-value="group.work_date ?? ''"
                    data-d1="listening-work-date"
                    :disabled="!canEdit"
                    @update:model-value="
                      setGroupField(group.group_id, 'work_date', String($event))
                    "
                  />
                </label>
                <label>
                  <span>一对一倾听记录</span>
                  <el-input
                    :model-value="group.listening_text ?? ''"
                    type="textarea"
                    :rows="5"
                    data-d1="listening-text"
                    :disabled="!canEdit"
                    @update:model-value="
                      setGroupField(group.group_id, 'listening_text', String($event))
                    "
                  />
                </label>
              </div>
            </div>
          </el-card>
        </div>

        <h3>领域评价</h3>
        <div
          v-for="item in template.items"
          :key="item.item_id"
          class="evaluation-row"
          :data-d1="`listening-item-${item.item_id}`"
        >
          <div class="evaluation-head">
            <strong>{{ item.requirement }}</strong>
            <span class="muted">{{ item.level1 }} / {{ item.level2 }}</span>
          </div>
          <div class="standards">
            <div><span class="star">★</span> {{ item.standards['1'] }}</div>
            <div><span class="star">★★</span> {{ item.standards['2'] }}</div>
            <div><span class="star">★★★</span> {{ item.standards['3'] }}</div>
          </div>
          <div class="star-actions">
            <el-button
              v-for="stars in [1, 2, 3]"
              :key="stars"
              size="small"
              :type="starsFor(item.item_id) === stars ? 'primary' : 'default'"
              :data-d1="`listening-star-${item.item_id}-${stars}`"
              :disabled="!canEdit"
              @click="setStars(item.item_id, stars)"
            >
              {{ '★'.repeat(stars) }}
            </el-button>
            <el-button
              size="small"
              text
              data-d1="listening-star-clear"
              :disabled="!canEdit || starsFor(item.item_id) === null"
              @click="setStars(item.item_id, null)"
            >
              清空
            </el-button>
          </div>
        </div>

        <div class="header-grid">
          <label class="wide">
            <span>综合评价</span>
            <el-input
              :model-value="form.overall_evaluation ?? ''"
              type="textarea"
              :rows="3"
              data-d1="listening-overall"
              :disabled="!canEdit"
              @update:model-value="setField('overall_evaluation', String($event))"
            />
          </label>
          <label class="wide">
            <span>支持策略</span>
            <el-input
              :model-value="form.support_strategy ?? ''"
              type="textarea"
              :rows="3"
              data-d1="listening-support"
              :disabled="!canEdit"
              @update:model-value="setField('support_strategy', String($event))"
            />
          </label>
        </div>
      </el-card>
    </template>

    <ListeningAiPanel
      v-if="state.loaded && form && template"
      :record-id="props.recordId"
      :domain="state.domain"
      :groups="form.groups"
      :revision="record?.revision ?? 0"
      :disabled="!canMutate || !!state.unknown"
      :profile-epoch="props.profileEpoch ?? 0"
      :ensure-saved="ensureAiSaved"
      @busy="handleAiBusy"
      @draft="handleAiDraft"
      @adopted="handleAiAdopted"
    />

    <ListeningExportDialog
      v-model="exportOpen"
      mode="record"
      :context="props.context"
      :term-id="exportTermId"
      :record-id="props.recordId"
      @busy="handleExportBusy"
    />
  </div>
</template>

<style scoped>
.listening-editor {
  padding: 16px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.identity {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.actions {
  display: flex;
  gap: 8px;
}
.block {
  margin-top: 12px;
}
.loading-block {
  padding: 24px;
  color: #6b7280;
}
.shared-name {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.domain-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.header-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.header-grid label,
.group-grid label,
.text-cell label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.header-grid .wide {
  grid-column: 1 / -1;
}
.groups {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.group-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.group-grid {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(260px, 1fr);
  gap: 14px;
}
.photo-preview {
  min-height: 140px;
  border: 1px dashed #d1d5db;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  overflow: hidden;
}
.photo-preview img {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
}
.photo-error {
  color: #b91c1c;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.file-label {
  display: inline-block;
  margin-top: 8px;
  padding: 6px 10px;
  border: 1px solid #409eff;
  color: #409eff;
  border-radius: 4px;
  cursor: pointer;
}
.file-label.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.file-label input {
  display: none;
}
.text-cell {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.evaluation-row {
  border-top: 1px solid #ebeef5;
  padding: 10px 0;
}
.evaluation-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.standards {
  margin-top: 4px;
  color: #4b5563;
  font-size: 13px;
}
.star {
  color: #b45309;
}
.star-actions {
  margin-top: 6px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.muted {
  color: #6b7280;
}
@media (max-width: 900px) {
  .header-grid {
    grid-template-columns: 1fr;
  }
  .group-grid {
    grid-template-columns: 1fr;
  }
}
</style>
