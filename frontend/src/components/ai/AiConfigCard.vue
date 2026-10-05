<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCard, ElForm, ElFormItem, ElInput, ElText } from 'element-plus'
import { auth } from '../../auth'
import * as api from '../../api'
import type { AiConfigOut } from '../../types'
import {
  aiErrorNotice,
  buildConfigDeletePayload,
  buildConfigPatchPayload,
  createEpochGuard,
  readyReasonText,
  readyStatusText,
} from './ai-settings-shared'

const emit = defineEmits<{
  (e: 'account-invalid'): void
}>()

// --- Server baseline vs page-local inputs ---------------------------------
// baseline      : last server-confirmed GET/PATCH/DELETE response (versions)
// baseUrl/model : draft inputs (kept raw, no trim anywhere)
// secretInput   : '' means "keep stored key" (secret omitted). A non-empty
//                 string is sent raw. The stored mask (********) is never
//                 written back into the input. Nothing here is persisted.

const guard = createEpochGuard()
const baseline = ref<AiConfigOut | null>(null)
const baselineLoading = ref(false)
const baseUrlInput = ref('')
const modelInput = ref('')
const secretInput = ref('')
const saving = ref(false)
const clearing = ref(false)
const confirmingClear = ref(false)
const alert = ref<{ type: 'error' | 'warning' | 'success' | 'info'; text: string } | null>(null)
// Set on 409: the freshest server state shown for comparison; inputs stay.
const conflictLatest = ref<AiConfigOut | null>(null)
// S4: true from a 409 until the user explicitly picks 载入最新/保留输入.
// While set, PATCH/DELETE are blocked (no repeated writes with stale
// versions); it survives a failed comparison GET so a safe recovery entry
// (重新获取最新配置) stays visible.
const conflictPending = ref(false)
// True while the first (or a retry) metadata read is failing; owning the
// retry row so the card never sits on a fake "loading" spinner.
const baselineError = ref(false)

const trackedAccount = ref<string | null>(auth.account?.id ?? null)

watch(
  () => auth.account?.id ?? null,
  (id) => {
    if (id === trackedAccount.value) return
    trackedAccount.value = id
    guard.bump()
    // New owner resets every flag the old epoch could leave dangling; the
    // old load/save/clear finallys are dead after bump and cannot unlock.
    baselineLoading.value = false
    saving.value = false
    clearing.value = false
    baselineError.value = false
    secretInput.value = ''
    baseUrlInput.value = ''
    modelInput.value = ''
    baseline.value = null
    conflictLatest.value = null
    conflictPending.value = false
    alert.value = null
    if (id !== null) void load()
  },
)

onBeforeUnmount(() => {
  // Unmount invalidates every in-flight op and wipes the in-memory secret
  // immediately (also the 401/exit path). Nothing is persisted anywhere.
  guard.bump()
  secretInput.value = ''
  alert.value = null
})

function applyResponse(out: AiConfigOut) {
  baseline.value = out
}

async function load() {
  const at = guard.token()
  baselineLoading.value = true
  baselineError.value = false
  try {
    const out = await api.getAiConfig()
    if (!guard.alive(at)) return
    // repair2 §5 declaration now matched by code (review correction): an
    // explicit re-read NEVER clears an active conflict view — the user
    // still picks 载入最新/保留输入 themselves. The template's load retry
    // rows live in the no-baseline branch anyway, where no conflict view
    // exists.
    const firstFill = baseline.value === null
    applyResponse(out)
    // First load populates the editable metadata from the server so a key
    // rotation alone submits the stored URL/model unchanged, not empty
    // strings. Later refreshes never touch the inputs (dirty stays dirty).
    if (firstFill) {
      baseUrlInput.value = out.base_url ?? ''
      modelInput.value = out.model ?? ''
    }
  } catch (err) {
    if (!guard.alive(at)) return
    baselineError.value = true
    const notice = aiErrorNotice(err as api.ApiError, '配置读取失败，请稍后重试。')
    alert.value = notice ? { type: 'error', text: notice } : null
    if ((err as api.ApiError).status === 401) {
      emit('account-invalid')
    }
  } finally {
    if (guard.alive(at)) baselineLoading.value = false
  }
}

async function save() {
  // form submit fires on Enter too — re-entry cannot rely on the disabled
  // button alone: check the write locks and the save preconditions here.
  if (saving.value || clearing.value || baselineLoading.value) return
  if (!baseline.value || !canSave.value) return
  if (conflictPending.value) {
    // S4: a pending conflict demands an explicit choice — another click is
    // never an implicit confirmation and must not re-send the old version.
    alert.value = { type: 'warning', text: '存在未处理的冲突：请先选择载入最新配置或保留输入，再保存。' }
    return
  }
  const at = guard.token()
  saving.value = true
  try {
    // Full metadata every time; payload assembly lives in the pure shared
    // helper (directed-check tested): empty secret input is omitted
    // entirely, non-empty input is sent raw, and expected_version is the
    // AI-config version, never the account version.
    const payload = buildConfigPatchPayload(
      baseline.value.version,
      baseUrlInput.value,
      modelInput.value,
      secretInput.value,
    )
    const out = await api.patchAiConfig(payload)
    if (!guard.alive(at)) return
    // Success closes any stale-conflict view and clears the in-memory
    // secret input; on failure it stays in memory only (never shown,
    // logged, or persisted).
    conflictLatest.value = null
    conflictPending.value = false
    secretInput.value = ''
    applyResponse(out)
    alert.value = { type: 'success', text: `配置已保存（版本 ${out.version}）。其中“就绪状态”只表示本地配置可用。` }
  } catch (err) {
    if (!guard.alive(at)) return
    await handleSaveFailure(err)
  } finally {
    if (guard.alive(at)) saving.value = false
  }
}

async function handleSaveFailure(err: unknown) {
  const e = err as api.ApiError
  if (e.status === 401) {
    secretInput.value = ''
    emit('account-invalid')
    return
  }
  noticeFailure(e)
  if (e.code === 'VERSION_CONFLICT') {
    // The comparison GET captures its own token BEFORE the await: a bump
    // (switch/unmount/account change) between the calls must kill this
    // response too — checking the CURRENT token here would always pass.
    const at2 = guard.token()
    try {
      const latest = await api.getAiConfig()
      if (!guard.alive(at2)) return
      conflictLatest.value = latest
      conflictPending.value = true
      alert.value = {
        type: 'warning',
        text: '配置刚被另一处保存过，您的输入已保留。请选择：载入最新配置，或保留输入并按最新版本重新保存（需要再点一次保存）。',
      }
    } catch (loadErr) {
      if (!guard.alive(at2)) return
      // S4: the comparison GET itself failed — the pending conflict stays
      // with a visible safe recovery entry (retry), inputs untouched.
      conflictPending.value = true
      const notice = aiErrorNotice(loadErr as api.ApiError, '最新配置获取失败，请稍后重试。')
      alert.value = {
        type: 'warning',
        text: `最新配置获取未完成${notice ? `（${notice}）` : ''}；您的输入已保留，可点击“重新获取最新配置”再选择。`,
      }
    }
  }
}

/** S4 recovery entry: re-fetch the server truth for the parked conflict. */
async function retryConflictLatest() {
  if (saving.value || clearing.value || baselineLoading.value) return
  const at2 = guard.token()
  try {
    const latest = await api.getAiConfig()
    if (!guard.alive(at2)) return
    conflictLatest.value = latest
    conflictPending.value = true
    alert.value = {
      type: 'warning',
      text: '已重新获取最新配置，请选择：载入最新配置，或保留输入并按最新版本重新保存（需要再点一次保存）。',
    }
  } catch (loadErr) {
    if (!guard.alive(at2)) return
    conflictPending.value = true
    const notice = aiErrorNotice(loadErr as api.ApiError, '最新配置获取失败，请稍后重试。')
    alert.value = {
      type: 'warning',
      text: `最新配置获取未完成${notice ? `（${notice}）` : ''}；您的输入已保留，可稍后再试。`,
    }
  }
}

function noticeFailure(e: api.ApiError) {
  const text = aiErrorNotice(e, '保存失败')
  alert.value = text ? { type: 'error', text } : null
}

/** Loads the latest server state into the inputs (explicit user action). */
function loadLatestIntoInputs() {
  const latest = conflictLatest.value
  if (!latest) return
  alert.value = { type: 'info', text: '已载入最新配置；密钥输入不会被回填，请检查后再次点击“保存配置”。' }
  conflictLatest.value = null
  conflictPending.value = false
  // The metadata rebase is explicit: the URL/model inputs really adopt the
  // server's latest values. The secret input is NEVER filled from the
  // server (the mask is not a value) and an unsubmitted in-progress key is
  // kept for the user to review — never silently dropped. Full key
  // plaintext never reaches this page either.
  baseUrlInput.value = latest.base_url ?? ''
  modelInput.value = latest.model ?? ''
  applyResponse({ ...latest, secret_mask: latest.has_secret ? '********' : null })
}

/** Rebases expected_version without touching any input (explicit action). */
function keepInputsRebaseVersion() {
  const latest = conflictLatest.value
  if (!latest) return
  alert.value = { type: 'info', text: '已按最新版本作为保存基线；请检查输入后再次点击“保存配置”。' }
  conflictLatest.value = null
  conflictPending.value = false
  applyResponse({ ...latest, secret_mask: latest.has_secret ? '********' : null })
}

async function clearSecret() {
  // Re-entry guard: the disabled button cannot cover every path.
  if (saving.value || clearing.value || baselineLoading.value) return
  const b = baseline.value
  if (!b) return
  // S4: a pending conflict demands an explicit choice first; the delete is
  // a write just like the PATCH and must not re-send a stale version.
  if (conflictPending.value) {
    alert.value = { type: 'warning', text: '存在未处理的冲突：请先选择载入最新配置或保留输入，再清除密钥。' }
    return
  }
  confirmingClear.value = false
  const at = guard.token()
  clearing.value = true
  try {
    const out = await api.deleteAiConfig(
      buildConfigDeletePayload(b.version),
    )
    if (!guard.alive(at)) return
    conflictLatest.value = null
    conflictPending.value = false
    secretInput.value = ''
    applyResponse(out)
    alert.value = { type: 'success', text: '已清除保存的密钥。API 地址和模型名称保留，完整密钥不会回显。' }
  } catch (err) {
    if (!guard.alive(at)) return
    await handleSaveFailure(err)
  } finally {
    if (guard.alive(at)) clearing.value = false
  }
}

function teardownSecretInput() {
  secretInput.value = ''
}

// --- ViewModel ------------------------------------------------------------

const infoRows = computed(() => {
  const c = baseline.value
  if (!c) return []
  const rows: Array<{ label: string; value: string }> = [
    { label: '保存版本', value: String(c.version) },
    {
      label: '接口协议',
      value: c.protocol_id ? 'OpenAI 兼容 chat/completions（本系统固定使用此协议）' : '未配置',
    },
    { label: 'API 地址', value: c.base_url || '未填写' },
    { label: '模型名称', value: c.model || '未填写' },
    {
      label: '已保存密钥',
      value: c.has_secret
        ? `已设置（仅显示固定遮罩 ${c.secret_mask ?? '********'}，完整密钥不回显）`
        : '未设置',
    },
    { label: '就绪状态', value: readyStatusText(c.ready, c.ready_reason) },
  ]
  if (!c.ready && c.ready_reason && c.ready_reason !== 'NOT_CONFIGURED') {
    rows.push({ label: '未就绪原因', value: readyReasonText(c.ready_reason) })
  }
  return rows
})

/**
 * A first save (no configuration head exists yet: version stays 0) must
 * carry a new key; after a clear (head exists but empty) metadata-only
 * saves are allowed to omit the key.
 */
const firstSaveNeedsSecret = computed(
  () => (baseline.value ? baseline.value.version === 0 : true),
)

const metadataDirty = computed(() => {
  if (!baseline.value) return false
  return (
    baseUrlInput.value !== (baseline.value.base_url ?? '') ||
    modelInput.value !== (baseline.value.model ?? '')
  )
})

const secretProvided = computed(() => secretInput.value !== '')

const canSave = computed(() => {
  if (baselineLoading.value || saving.value || clearing.value) return false
  // S4: an unresolved conflict blocks repeated writes until the user picks
  // 载入最新/保留输入 explicitly (a failed comparison GET keeps this on).
  if (conflictLatest.value || conflictPending.value) return false
  if (!baseline.value) return false
  if (firstSaveNeedsSecret.value) return secretProvided.value
  // After adopting the latest version deliberately, a fully clean form has
  // nothing new to submit (it would only burn a version).
  return metadataDirty.value || secretProvided.value
})

const canClear = computed(() => {
  if (baselineLoading.value || saving.value || clearing.value) return false
  // Same pending-conflict gate as the save path (S4).
  if (conflictLatest.value || conflictPending.value) return false
  const b = baseline.value
  // Nothing to clear before any head exists or while no key is stored.
  return !!b && b.version > 0 && b.has_secret
})

/**
 * Public surface used by SettingsView: wipe the in-memory key (401/exit)
 * and report unsaved input so leaving the page can demand confirmation.
 */
defineExpose({
  teardownSecretInput,
  hasUnsavedChanges: () => secretInput.value !== '' || metadataDirty.value,
})

// First read-only GET right at setup: the card is mounted on the settings
// page with the tracked account already current, so the watcher alone
// never fires. Without this the page would show "正在读取配置…" forever.
void load()
</script>

<template>
  <el-card data-testid="ai-config-card">
    <template #header>我的 AI 服务配置</template>

    <el-alert
      v-if="alert"
      :closable="true"
      :type="alert.type"
      :title="alert.text"
      show-icon
      class="alert"
      @close="alert = null"
    />

    <div v-if="baseline">
      <div class="facts">
        <div class="fact" v-for="row in infoRows" :key="row.label">
          <span class="fact-label">{{ row.label }}</span>
          <span class="fact-value">{{ row.value }}</span>
        </div>
      </div>

      <el-form label-position="top" @submit.prevent="save">
        <el-form-item label="API 地址（仅允许公网 HTTPS 地址）">
          <el-input
            v-model="baseUrlInput"
            :placeholder="baseline.base_url ? '' : 'https://…（公网 HTTPS 地址）'"
            maxlength="500"
            autocomplete="off"
          />
          <ElText v-if="conflictLatest" type="warning" size="small" class="hint">
            服务端最新地址：{{ conflictLatest.base_url || '（未填写）' }}
          </ElText>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input
            v-model="modelInput"
            maxlength="200"
            autocomplete="off"
            :placeholder="baseline.model ? '' : '例如服务商提供的模型名称'"
          />
          <ElText v-if="conflictLatest" type="warning" size="small" class="hint">
            服务端最新模型：{{ conflictLatest.model || '（未填写）' }}
          </ElText>
        </el-form-item>
        <el-form-item label="密钥（留空表示不更换已保存的密钥）">
          <el-input
            v-model="secretInput"
            type="password"
            autocomplete="new-password"
            show-password
            placeholder="首次设置或更换密钥时才填写；清除请使用专门操作"
          />
          <div class="hint">
            已保存密钥始终回显为固定遮罩 ********，完整密钥不会显示在页面上。
            <template v-if="firstSaveNeedsSecret"> 首次保存必须填写新密钥。</template>
            <template v-else> 留空提交即保留当前已保存的密钥。</template>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :disabled="!canSave" :loading="saving">保存配置</el-button>
          <el-button :disabled="!canClear" :loading="clearing" @click="confirmingClear = true">清除已保存密钥</el-button>
        </el-form-item>
      </el-form>

      <div v-if="confirmingClear" class="confirm-clear">
        <el-alert
          type="warning"
          :closable="false"
          title="确认清除已保存密钥？清除后需重新设置密钥才能使用 AI 相关功能；API 地址与模型不会被删除。"
        />
        <div class="confirm-actions">
          <el-button type="danger" :loading="clearing" @click="clearSecret">确认清除</el-button>
          <el-button @click="confirmingClear = false">取消</el-button>
        </div>
      </div>

      <div v-if="conflictLatest" class="conflict-actions">
        <el-button :disabled="saving || clearing" @click="loadLatestIntoInputs">载入最新配置</el-button>
        <el-button :disabled="saving || clearing" @click="keepInputsRebaseVersion">保留输入，按最新版本重新保存</el-button>
      </div>
      <!-- S4: safe recovery entry when the conflict comparison GET failed -->
      <div v-if="conflictPending && !conflictLatest" class="conflict-actions">
        <el-text type="warning" size="small">最新配置获取未完成；您的输入已保留。</el-text>
        <el-button :disabled="saving || clearing || baselineLoading" @click="retryConflictLatest">重新获取最新配置</el-button>
      </div>
      <!-- S4: the safe recovery entry when the conflict comparison GET
           itself failed — visible until the server truth arrives, inputs
           stay untouched. -->
      <div v-if="conflictPending && !conflictLatest" class="conflict-actions">
        <el-text type="warning" size="small">最新配置获取未完成；您的输入已保留。</el-text>
        <el-button :disabled="saving || clearing || baselineLoading" @click="retryConflictLatest">重新获取最新配置</el-button>
      </div>
      <div class="hint plain-hint">
        本页面不发起任何 AI 调用，也没有“测试连接”按钮；保存设置本身不调用供应商、不产生调用费用，开启 AI 功能后按需处理各自操作。
      </div>
    </div>

    <div v-else class="loading-row">
      <el-button v-if="baselineLoading" :loading="true" text>正在读取配置…</el-button>
      <template v-else>
        <el-button v-if="baselineError" type="warning" text @click="load()">读取失败，重新读取</el-button>
        <el-button v-else text :disabled="baselineLoading" @click="load()">重新读取</el-button>
      </template>
    </div>
  </el-card>
</template>

<style scoped>
.alert { margin-bottom: 16px; }
.facts { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.fact { display: flex; gap: 12px; font-size: 0.92rem; line-height: 1.5; }
.fact-label { color: #909399; min-width: 7em; flex-shrink: 0; }
.fact-value { color: #303133; white-space: pre-wrap; word-break: break-all; }
.hint { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; display: block; }
.plain-hint { margin-top: 8px; }
.confirm-clear { margin-top: 8px; }
.confirm-actions { display: flex; gap: 8px; margin-top: 8px; }
.conflict-actions { margin-top: 8px; display: flex; gap: 8px; }
.loading-row { display: flex; align-items: center; gap: 12px; }
</style>
