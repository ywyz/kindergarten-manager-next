<script setup lang="ts">
/**
 * In-app online feedback panel (desktop-webdav-and-online-feedback spec).
 *
 * The teacher sees the exact content that would be sent (application version
 * plus their own trimmed input) before an explicit submit; the submission
 * also carries the feedback code and one request identifier, and nothing
 * else is auto-collected.  While a submission is in flight the three inputs
 * are locked, so the response can never clear input typed afterwards.  A
 * failed or unknown outcome keeps the whole form; the client-generated
 * request id stays fixed until the outcome is known, so a retry resolves to
 * the same receipt and never creates a duplicate admin entry.  A receipt is
 * only accepted when it answers exactly this request with a valid id and
 * time; anything else stays an unknown outcome.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import { getFeedbackStatus, submitFeedback } from '../feedback'
import type { FeedbackReceipt, FeedbackStatus } from '../feedback'

const props = defineProps<{ frozen?: boolean }>()

const MAX_CONTENT_CHARS = 4000
const MAX_CONTACT_CHARS = 200
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const status = ref<FeedbackStatus | null>(null)
const statusError = ref('')
const feedbackCode = ref('')
const content = ref('')
const contact = ref('')
const submitting = ref(false)
const errorText = ref('')
const receipt = ref<FeedbackReceipt | null>(null)
const unknownOutcome = ref(false)
/** Fixed while a submission's outcome is unknown; cleared on any edit. */
let pendingRequestId = ''

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

function clearPendingForEdit(): void {
  pendingRequestId = ''
  unknownOutcome.value = false
}

watch([feedbackCode, content, contact], () => clearPendingForEdit())

onMounted(async () => {
  statusError.value = ''
  try {
    status.value = await getFeedbackStatus()
  } catch (err) {
    statusError.value = err instanceof ApiError
      ? err.message
      : '反馈服务状态读取失败，请稍后重试'
  }
})

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
  const code = feedbackCode.value.trim()
  if (!code) {
    errorText.value = '请输入测试组织者分发的反馈码'
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
  if (!pendingRequestId) pendingRequestId = crypto.randomUUID()
  // The exact request this submission belongs to; the receipt must match it.
  const requestId = pendingRequestId
  submitting.value = true
  try {
    const result = await submitFeedback({
      request_id: requestId,
      feedback_code: code,
      content: text,
      contact: cleanContact ? cleanContact : null,
    })
    if (!validReceipt(result, requestId)) {
      // An unrecognizable answer leaves the outcome unknown: the form and
      // the same request id are kept for an explicit retry.
      unknownOutcome.value = true
      errorText.value =
        '提交结果未确认：服务端返回的回执与本次请求不一致。表单内容已保留，可点击“用同一请求再次提交”核对或重试。'
      return
    }
    receipt.value = result
    content.value = ''
    contact.value = ''
    pendingRequestId = ''
    unknownOutcome.value = false
  } catch (err) {
    if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
      // The outcome is unknown (network failure or upstream trouble): the
      // form and the same request id are kept so a retry either resolves the
      // original receipt or submits safely for the first time.
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
        <label>反馈码（由测试组织者分发）</label>
        <el-input
          v-model="feedbackCode"
          maxlength="512"
          :disabled="frozen || !configured || submitting"
          data-d1="feedback-code"
        />
      </div>
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
      <p>反馈码：{{ feedbackCode.trim() ? '已填写' : '（尚未填写）' }}</p>
      <p class="muted">
        提交会发送：以上反馈信息、应用版本、联系方式（可选）、反馈码，以及一个仅用于防重复提交的请求标识；不会自动收集教师档案、幼儿记录、图片、数据库、凭据或日志。
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
      <p class="muted">提交期间输入会短暂锁定；失败或结果未知时表单内容保留，可用同一请求再次提交。</p>
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
