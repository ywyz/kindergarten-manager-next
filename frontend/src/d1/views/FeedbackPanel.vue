<script setup lang="ts">
/**
 * In-app online feedback panel (desktop-webdav-and-online-feedback spec).
 *
 * The teacher sees the exact content that would be sent (application version
 * plus their own trimmed input) before an explicit submit; the submission
 * also carries one request identifier, and — since 2026-11-24, and only
 * while the teacher keeps the attach choice on — the recent local
 * diagnostics events, rendered in an expandable preview that shows exactly
 * the events that would be sent.  Cancelling the attach removes the events
 * from the payload entirely.  No feedback code is sent or asked for.  While
 * a submission is in flight the inputs are locked, so the response can never
 * clear input typed afterwards.  A failed or unknown outcome keeps the whole
 * form: the client-generated request id and the frozen diagnostics snapshot
 * stay fixed until the outcome is known, so a retry resolves to the same
 * receipt and never creates a duplicate admin entry.  Editing the content
 * or changing the attach choice starts a new intent (a new request id).
 * A receipt is only accepted when it answers exactly this request with a
 * valid id and time; anything else stays an unknown outcome.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import {
  getFeedbackDiagnosticsEvents,
  getFeedbackStatus,
  submitFeedback,
} from '../feedback'
import type {
  FeedbackDiagnosticsEvent,
  FeedbackReceipt,
  FeedbackStatus,
} from '../feedback'

const props = defineProps<{ frozen?: boolean; open?: boolean }>()

const MAX_CONTENT_CHARS = 4000
const MAX_CONTACT_CHARS = 200
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
// The fixed event-type vocabulary, kept in sync with the shared contract
// (backend/app/diagnostics_contract.py).
const EVENT_TYPE_PATTERN = /^(export_word|local_backup|webdav_backup|update_check|update_download|save_daily_plan|save_weekly_plan|save_observation|save_listening|save_curriculum)$/
const RESULT_PATTERN = /^(ok|canceled|failed|unknown)$/
const CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/
const TIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/

const EVENT_TYPE_LABELS: Record<string, string> = {
  export_word: '导出 Word',
  local_backup: '本机备份',
  webdav_backup: 'WebDAV 备份',
  update_check: '更新检查',
  update_download: '更新下载',
  save_daily_plan: '保存日计划',
  save_weekly_plan: '保存周计划',
  save_observation: '保存观察记录',
  save_listening: '保存倾听记录',
  save_curriculum: '保存课程审议',
}

const RESULT_LABELS: Record<string, string> = {
  ok: '成功',
  canceled: '已取消',
  failed: '失败',
  unknown: '结果未知',
}

const status = ref<FeedbackStatus | null>(null)
const statusError = ref('')
const content = ref('')
const contact = ref('')
const submitting = ref(false)
const errorText = ref('')
const receipt = ref<FeedbackReceipt | null>(null)
const unknownOutcome = ref(false)
/** Fixed while a submission's outcome is unknown; cleared on any intent edit. */
let pendingRequestId = ''
/**
 * Frozen diagnostics for the pending intent.  ``null`` means this intent
 * attaches none; the flag pair keeps "no intent yet" distinguishable.
 */
let pendingDiagnostics: FeedbackDiagnosticsEvent[] | null = null
let pendingIntentActive = false

// Diagnostics attach state (default: attached).
const diagEvents = ref<FeedbackDiagnosticsEvent[]>([])
const diagUnavailable = ref(false)
const diagLoading = ref(false)
const attachDiagnostics = ref(true)
const diagPreviewOpen = ref(false)

const configured = computed(() => status.value?.configured === true)
const unconfiguredMessage = computed(
  () => status.value?.message || '未配置反馈服务地址，请联系部署方',
)

const appVersionText = computed(() => {
  const version = status.value?.app_version?.trim()
  return version ? version : '（未知）'
})

const contactPreview = computed(() => {
  const value = contact.value.trim()
  return value ? value : '（不发送联系信息）'
})

/** Exactly the content text that submit() would send. */
const contentPreview = computed(() => {
  const value = content.value.trim()
  return value ? value : '（尚未填写）'
})

function validEvent(value: unknown): value is FeedbackDiagnosticsEvent {
  if (value === null || typeof value !== 'object') return false
  const event = value as Record<string, unknown>
  return (
    typeof event.event_type === 'string'
    && EVENT_TYPE_PATTERN.test(event.event_type)
    && typeof event.time === 'string'
    && TIME_PATTERN.test(event.time)
    && !Number.isNaN(Date.parse(event.time))
    && typeof event.result === 'string'
    && RESULT_PATTERN.test(event.result)
    && (event.result === 'failed' || event.result === 'unknown'
      ? typeof event.error_code === 'string' && CODE_PATTERN.test(event.error_code)
      : event.error_code === null)
  )
}

function eventLabel(event: FeedbackDiagnosticsEvent): string {
  const code = event.error_code ? `（${event.error_code}）` : ''
  return `${event.time} · ${EVENT_TYPE_LABELS[event.event_type] || event.event_type} · ${RESULT_LABELS[event.result] || event.result}${code}`
}

/** Exactly the diagnostics list that submit() would send right now. */
const attachPreviewEvents = computed<FeedbackDiagnosticsEvent[]>(() => {
  if (pendingIntentActive) return pendingDiagnostics ?? []
  return attachDiagnostics.value ? diagEvents.value : []
})

const attachedCount = computed(() => attachPreviewEvents.value.length)

const attachNote = computed(() => {
  if (pendingIntentActive) {
    return pendingDiagnostics
      ? `上次提交尚未确认：重试会原样发送这 ${pendingDiagnostics.length} 条`
      : '上次提交尚未确认：该次未附带诊断日志，重试仍不附带'
  }
  if (diagLoading.value) {
    return '诊断日志加载中…（可直接提交不带日志的反馈）'
  }
  if (diagUnavailable.value) {
    return '诊断日志读取失败：本次不会附带任何日志，可直接提交'
  }
  if (!attachDiagnostics.value) {
    return '已取消附带：本次反馈不包含任何日志'
  }
  return diagEvents.value.length
    ? `默认附带：将随反馈发送以下 ${diagEvents.value.length} 条`
    : '近期没有可附着的诊断事件：本次不附带日志，可直接提交'
})

function clearPendingForEdit(): void {
  pendingRequestId = ''
  pendingDiagnostics = null
  pendingIntentActive = false
  unknownOutcome.value = false
}

watch([content, contact, attachDiagnostics], () => clearPendingForEdit())

async function loadDiagnostics(): Promise<void> {
  diagUnavailable.value = false
  diagLoading.value = true
  try {
    const snapshot = await getFeedbackDiagnosticsEvents()
    const events = Array.isArray(snapshot?.events) ? snapshot.events : []
    diagEvents.value = events.filter(validEvent)
  } catch {
    diagEvents.value = []
    diagUnavailable.value = true
  } finally {
    diagLoading.value = false
  }
}

onMounted(async () => {
  statusError.value = ''
  try {
    status.value = await getFeedbackStatus()
  } catch (err) {
    statusError.value = err instanceof ApiError
      ? err.message
      : '反馈服务状态读取失败，请稍后重试'
  }
  void loadDiagnostics()
})

// Each dialog open refreshes the attachable window (the panel instance
// itself survives close/reopen).  A pending unknown-outcome intent is never
// touched here: its frozen snapshot belongs to its fixed request id.
watch(
  () => props.open,
  (value) => {
    if (value) void loadDiagnostics()
  },
)

/** A receipt is only trusted when it answers exactly this submission. */
function validReceipt(
  value: FeedbackReceipt | null | undefined,
  requestId: string,
): value is FeedbackReceipt {
  return (
    value !== null
    && value !== undefined
    && value.request_id === requestId
    && typeof value.submission_id === 'string'
    && UUID_PATTERN.test(value.submission_id)
    && typeof value.received_at === 'string'
    && !Number.isNaN(Date.parse(value.received_at))
  )
}

async function submit(): Promise<void> {
  if (props.frozen || submitting.value) return
  if (!configured.value) {
    errorText.value = unconfiguredMessage.value
    return
  }
  const text = content.value.trim()
  if (!text) {
    errorText.value = '请填写问题或建议内容'
    return
  }
  const cleanContact = contact.value.trim()
  errorText.value = ''
  unknownOutcome.value = false
  if (!pendingRequestId) {
    // Freeze this intent: the same request id keeps the same diagnostics
    // until its outcome is known, so a retry replays one submission.
    pendingRequestId = crypto.randomUUID()
    pendingIntentActive = true
    pendingDiagnostics =
      attachDiagnostics.value && diagEvents.value.length
        ? diagEvents.value.map((event) => ({ ...event }))
        : null
  }
  // The exact request this submission belongs to; the receipt must match it.
  const requestId = pendingRequestId
  const input: {
    request_id: string
    content: string
    contact: string | null
    diagnostics?: FeedbackDiagnosticsEvent[]
  } = {
    request_id: requestId,
    content: text,
    contact: cleanContact ? cleanContact : null,
  }
  if (pendingDiagnostics) input.diagnostics = pendingDiagnostics
  submitting.value = true
  try {
    const result = await submitFeedback(input)
    if (!validReceipt(result, requestId)) {
      // An unrecognizable answer leaves the outcome unknown: the form, the
      // same request id and the same frozen diagnostics are kept for an
      // explicit retry.
      unknownOutcome.value = true
      errorText.value =
        '提交结果未确认：服务端返回的回执与本次请求不一致。表单内容已保留，可点击“用同一请求再次提交”核对或重试。'
      return
    }
    receipt.value = result
    content.value = ''
    contact.value = ''
    pendingRequestId = ''
    pendingDiagnostics = null
    pendingIntentActive = false
    unknownOutcome.value = false
    // The next feedback starts from a fresh attachable window (recent
    // events recorded while this one was being written are picked up).
    void loadDiagnostics()
  } catch (err) {
    if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
      // The outcome is unknown (network failure or upstream trouble): the
      // form, the same request id and the same frozen diagnostics are kept
      // so a retry either resolves the original receipt or submits safely
      // for the first time.
      unknownOutcome.value = true
      errorText.value =
        '提交结果未知：表单内容已保留。可点击“用同一请求再次提交”核对或重试；不会产生重复反馈。'
      return
    }
    errorText.value = err instanceof ApiError
      ? err.message
      : '提交失败：表单内容已保留，请稍后重试'
  } finally {
    submitting.value = false
  }
}

function dismissReceipt(): void {
  receipt.value = null
}
</script>

<template>
  <div class="feedback-panel" data-d1="feedback">
    <el-alert
      v-if="statusError"
      type="error"
      :closable="false"
      data-d1="feedback-status-error"
      :title="statusError"
    />
    <el-alert
      v-else-if="status && !configured"
      type="warning"
      :closable="false"
      data-d1="feedback-unconfigured"
      :title="unconfiguredMessage"
    />
    <el-alert
      v-if="receipt"
      type="success"
      :closable="false"
      class="section"
      data-d1="feedback-receipt"
    >
      <template #title>
        已提交：回执编号 {{ receipt.submission_id }}（{{ receipt.received_at }}）
      </template>
      <p class="muted">
        {{
          receipt.replayed
            ? '此请求此前已被服务端收到，这里返回的是原回执；没有产生重复反馈。'
            : '服务端已收到该反馈。'
        }}
      </p>
      <el-button size="small" text data-d1="feedback-receipt-close" @click="dismissReceipt">
        关闭回执
      </el-button>
    </el-alert>

    <el-alert
      v-if="unknownOutcome"
      type="warning"
      :closable="false"
      class="section"
      data-d1="feedback-unknown-outcome"
      title="上次提交结果未知：表单已保留，可用同一请求再次提交核对或重试。"
    />

    <div class="fields">
      <div class="field">
        <label>联系方式（可选，最多 {{ MAX_CONTACT_CHARS }} 字）</label>
        <el-input
          v-model="contact"
          :maxlength="MAX_CONTACT_CHARS"
          placeholder="例如：邮箱或其他联系方式"
          :disabled="frozen || !configured || submitting"
          data-d1="feedback-contact"
        />
      </div>
      <div class="field field-wide">
        <label>问题或建议（最多 {{ MAX_CONTENT_CHARS }} 字）</label>
        <el-input
          v-model="content"
          type="textarea"
          :rows="6"
          :maxlength="MAX_CONTENT_CHARS"
          show-word-limit
          placeholder="例如：点了保存后没有反应"
          :disabled="frozen || !configured || submitting"
          data-d1="feedback-content"
        />
      </div>
    </div>

    <div class="preview-block" data-d1="feedback-preview">
      <h4>将发送的内容（点击提交前请核对）</h4>
      <p>应用版本：{{ appVersionText }}</p>
      <p class="pre-wrap">反馈信息：{{ contentPreview }}</p>
      <p>联系方式：{{ contactPreview }}</p>
      <div class="diag-block" data-d1="feedback-diagnostics-block">
        <label class="diag-toggle">
          <input
            type="checkbox"
            :checked="attachDiagnostics"
            :disabled="frozen || !configured || submitting"
            data-d1="feedback-diagnostics-toggle"
            @change="attachDiagnostics = ($event.target as HTMLInputElement).checked"
          />
          附带诊断日志
        </label>
        <el-button
          size="small"
          text
          data-d1="feedback-diagnostics-preview-toggle"
          :disabled="frozen || !configured || submitting"
          @click="diagPreviewOpen = !diagPreviewOpen"
        >
          {{ diagPreviewOpen ? '收起日志' : '查看日志' }}
        </el-button>
        <div v-if="diagPreviewOpen" class="diag-preview" data-d1="feedback-diagnostics-preview">
          <p class="muted">{{ attachNote }}</p>
          <template v-if="attachedCount > 0">
            <p class="muted">预览即发送内容（仅固定事件类型、时间、结果和固定错误码）：</p>
            <p
              v-for="(event, index) in attachPreviewEvents"
              :key="index"
              class="pre-wrap"
            >{{ eventLabel(event) }}</p>
          </template>
        </div>
      </div>
      <p class="muted">
        提交会发送：以上反馈信息、应用版本、联系方式（可选），以及「查看日志」中确认附着的诊断日志（如有）；不会自动收集教师档案、幼儿记录、图片、数据库、凭据或原始日志。
      </p>
    </div>

    <el-alert v-if="errorText" type="error" :closable="false" class="section" data-d1="feedback-error" :title="errorText" />

    <div class="row">
      <el-button
        data-d1="feedback-submit"
        type="primary"
        :loading="submitting"
        :disabled="frozen || !configured"
        @click="submit"
      >
        确认提交反馈
      </el-button>
      <p class="muted">提交期间输入会短暂锁定；失败或结果未知时表单内容保留。</p>
    </div>
  </div>
</template>

<style scoped>
.feedback-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fields {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1 1 220px;
}
.field-wide {
  flex-basis: 100%;
}
.field label {
  font-size: 0.85rem;
  color: var(--kgm-muted);
}
.preview-block {
  border: 1px solid var(--kgm-border);
  border-radius: 8px;
  padding: 12px 16px;
  background: var(--el-bg-color-page, #f7f9fa);
}
.preview-block h4 {
  margin: 0 0 8px;
  font-size: 0.9rem;
}
.preview-block p {
  margin: 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.diag-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
}
.diag-toggle {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 0.85rem;
  color: var(--kgm-text);
}
.diag-preview {
  border: 1px dashed var(--kgm-border);
  border-radius: 6px;
  padding: 8px 12px;
  margin-top: 4px;
}
.row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
.section {
  margin-top: 0;
}
</style>
