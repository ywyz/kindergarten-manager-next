<script setup lang="ts">
/**
 * D0 桌面验证窗口（合成数据）——仅供 D0 可行性验证使用，不代表每日活动计划
 * 已实现。会话令牌只保存在本页内存（client.ts 模块变量），不出现在 URL。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, hasSessionToken } from './client'
import {
  collectSession,
  type EnvironmentInfo,
  setHostSaveDefaultFilename,
  type ProbeState,
  waitForHostSession,
} from './helpers'

const sessionReady = ref(false)
const sessionError = ref('')
const environment = ref<EnvironmentInfo | null>(null)
const envLoading = ref(false)
const probeContent = ref('')
// ``probeState`` is the last known SAVED record; ``probeContent`` is the
// user's editing input. They are kept separate so a failed save never
// overwrites the pending input with the old value (R5).
const probeState = ref<ProbeState | null>(null)
const saving = ref(false)
const saveResultText = ref('')
const saveResultOk = ref(false)
const saveSeq = ref(0)
const simulateFailure = ref(false)
const wordSaving = ref(false)
const wordResultText = ref('')
const wordResultOk = ref(false)
const wordSeq = ref(0)

const hostMode = computed(() =>
  environment.value?.frozen ? '打包运行（PyInstaller 目录模式）' : '开发环境运行（仓库源码）',
)

async function loadEnvironment(): Promise<void> {
  envLoading.value = true
  const result = await apiGet<EnvironmentInfo>('/api/probe/environment')
  envLoading.value = false
  if (result.ok) {
    environment.value = result.data
  } else {
    saveResultText.value = `环境信息读取失败：${result.message}`
    saveResultOk.value = false
  }
}

/** Refresh the saved-record display; only sync the input when asked (R5). */
async function readState(syncInput = false): Promise<void> {
  const result = await apiGet<ProbeState>('/api/probe/state')
  if (result.ok) {
    probeState.value = result.data as ProbeState
    if (syncInput && result.data.status === 'ok') {
      probeContent.value = (result.data.content as string) ?? ''
    }
  }
}

async function saveState(): Promise<void> {
  saving.value = true
  saveResultText.value = ''
  const result = await apiPost<{ status: string; version: number }>(
    '/api/probe/state',
    { content: probeContent.value, simulate_failure: simulateFailure.value },
  )
  saving.value = false
  if (result.ok) {
    saveResultOk.value = true
    saveResultText.value = `保存成功（版本 ${result.data.version}）`
  } else {
    saveResultOk.value = false
    // 未保存不得显示为保存成功；明确失败文案，输入保持用户当前内容。
    saveResultText.value = `保存失败：${result.message}`
  }
  // Refresh the saved-record view WITHOUT touching the editing input: on
  // failure the DB still holds the previous content and the pending input is
  // preserved for an explicit retry.
  await readState(false)
  saveSeq.value += 1
  ;(window as unknown as Record<string, unknown>).__d0SaveResult = {
    ok: saveResultOk.value,
    message: saveResultText.value,
    seq: saveSeq.value,
  }
}

async function exportWord(): Promise<void> {
  wordSaving.value = true
  wordResultText.value = ''
  const result = await apiPost<{
    filename: string
    payload_base64: string
    bytes: number
  }>('/api/probe/export', {})
  if (!result.ok) {
    wordSaving.value = false
    wordResultOk.value = false
    wordResultText.value = `DOCX 生成失败：${result.message}`
    recordWordResult('failed', undefined, wordResultText.value)
    return
  }
  setHostSaveDefaultFilename(result.data.filename)
  const pywebviewGlobal = (window as unknown as {
    pywebview?: {
      api?: { save_docx: (payload: unknown) => Promise<{ status: string; path?: string; message?: string }> }
    }
  }).pywebview
  if (!pywebviewGlobal?.api) {
    wordSaving.value = false
    wordResultOk.value = false
    wordResultText.value = '未找到桌面宿主接口（pywebview），请在 D0 桌面验证包中运行。'
    recordWordResult('failed', undefined, wordResultText.value)
    return
  }
  const payload: Record<string, unknown> = {
    payload_base64: result.data.payload_base64,
    filename: result.data.filename,
  }
  // Verification-only hook set by the automated driver: when present, the
  // host save is directed at the pre-authorized autosave directory. The
  // real page export entry and its /api call still run unchanged.
  const autosaveTarget = (window as unknown as Record<string, unknown>).__d0AutosaveTarget
  if (typeof autosaveTarget === 'string' && autosaveTarget) {
    payload.autosave_target = autosaveTarget
  }
  const save = await pywebviewGlobal.api.save_docx(payload)
  wordSaving.value = false
  if (save.status === 'saved') {
    wordResultOk.value = true
    wordResultText.value = `已保存：${save.path}`
    recordWordResult('saved', save.path, undefined)
  } else if (save.status === 'canceled') {
    wordResultOk.value = false
    wordResultText.value = '已取消保存（未成功，未生成文件）'
    recordWordResult('canceled', undefined, undefined)
  } else {
    wordResultOk.value = false
    wordResultText.value = `保存失败：${save.message ?? '未知原因'}`
    recordWordResult('failed', undefined, save.message ?? wordResultText.value)
  }
}

function recordWordResult(status: string, path?: string, message?: string): void {
  wordSeq.value += 1
  ;(window as unknown as Record<string, unknown>).__d0WordResult = {
    status,
    path,
    message,
    seq: wordSeq.value,
  }
}

onMounted(async () => {
  const stage = (window as unknown as Record<string, unknown>)
  stage.__d0MountStage = 'mounted-start'
  try {
    const bridge = await waitForHostSession()
    stage.__d0MountStage = bridge === 'ready' ? 'host-ready' : 'host-timeout'
    const session = await collectSession()
    if (bridge !== 'ready' || !hasSessionToken()) {
      sessionError.value =
        bridge === 'timeout'
          ? '未在超时时间内取得桌面宿主接口：请在 D0 桌面验证包中打开本窗口。'
          : '未取得应用会话：请在 D0 桌面验证包中打开本窗口（普通浏览器不会获得受保护的会话）。'
    } else {
      sessionReady.value = true
      sessionError.value = ''
      stage.__d0MountStage = 'loading-env'
      await loadEnvironment()
      stage.__d0MountStage = 'loading-state'
      await readState(true)
      stage.__d0MountStage = 'ready'
    }
  } catch (err) {
    sessionError.value = `初始化失败：${String(err)}`
    stage.__d0MountStage = `error:${String(err)}`
  } finally {
    // Always mark the page ready so the driver can report the real state
    // instead of timing out silently.
    stage.__d0PageReady = true
  }
})

function refreshError(message: string): void {
  ElMessage.error(message)
}
void refreshError
</script>

<template>
  <div class="d0-page">
    <h1>D0 桌面可行性验证窗口（合成数据）</h1>
    <el-alert
      type="info"
      :closable="false"
      title="D0 技术探针入口"
      description="本窗口只用于验证桌面容器、本地 API、SQLite 与 Word 保存，不含真实业务数据。"
      show-icon
    />

    <el-card class="block" shadow="never" data-d0="session-card">
      <template #header><span>应用会话（每次启动重新生成）</span></template>
      <p v-if="sessionReady" data-d0="session-ok">窗口会话已建立（令牌仅保存在窗口内存中）。</p>
      <el-alert
        v-else
        type="warning"
        :closable="false"
        data-d0="session-missing"
        :title="sessionError || '正在等待窗口会话……'"
        show-icon
      />
    </el-card>

    <el-card class="block" shadow="never">
      <template #header><span>运行环境信息</span></template>
      <el-descriptions v-if="environment" :column="1" size="small" border>
        <el-descriptions-item label="运行模式">{{ hostMode }}</el-descriptions-item>
        <el-descriptions-item label="WebView2 Runtime">
          {{ environment.webview2_runtime_version ?? '未检测到' }}
        </el-descriptions-item>
        <el-descriptions-item label="Python">{{ environment.python_version }}</el-descriptions-item>
        <el-descriptions-item label="SQLite 库版本">
          {{ environment.sqlite_library_version }}
        </el-descriptions-item>
        <el-descriptions-item label="驱动">
          {{ environment.dialect }} + {{ environment.driver }}（pysqlite {{
            environment.pysqlite_module_version
          }}）
        </el-descriptions-item>
        <el-descriptions-item label="外键开关">
          PRAGMA foreign_keys = {{ environment.foreign_keys_pragma }}
        </el-descriptions-item>
        <el-descriptions-item label="journal_mode">{{ environment.journal_mode }}</el-descriptions-item>
        <el-descriptions-item label="事务方式">{{ environment.transaction_style }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">
          {{ environment.data_dir }}
          <div class="muted">独立于程序解包目录。</div>
        </el-descriptions-item>
      </el-descriptions>
      <p v-else>环境信息只在会话建立后显示（无会话时不暴露数据）。</p>
    </el-card>

    <el-card class="block" shadow="never">
      <template #header><span>SQLite 合成探针</span></template>
      <el-input
        v-model="probeContent"
        type="textarea"
        :rows="3"
        placeholder="输入合成探针内容（仅在验证库中保存）"
        data-d0="probe-content"
      />
      <div class="actions">
        <el-button
          type="primary"
          data-d0="save-state"
          :loading="saving"
          @click="saveState"
        >
          保存探针记录
        </el-button>
        <el-button :disabled="saving" @click="readState(true)">读取当前记录</el-button>
        <el-checkbox v-model="simulateFailure" data-d0="simulate-failure">
          模拟写入失败
        </el-checkbox>
      </div>
      <p data-d0="save-result" :data-d0-seq="saveSeq" :class="saveResultOk ? 'ok' : 'fail'">
        {{ saveResultText || '尚未保存。' }}
      </p>
      <p v-if="probeState?.status === 'ok'" class="muted">
        当前记录：内容「{{ probeState.content }}」；版本 {{ probeState.version }}；写入时间
        {{ probeState.updated_at }}。
      </p>
      <p v-else class="muted" data-d0="probe-empty">暂无记录。</p>
    </el-card>

    <el-card class="block" shadow="never">
      <template #header><span>Word 保存（合成日计划，窗口原生保存对话框）</span></template>
      <el-button
        type="primary"
        data-d0="save-word"
        :loading="wordSaving"
        @click="exportWord"
      >
        生成并保存日计划 DOCX
      </el-button>
      <p data-d0="word-result" :data-d0-word-seq="wordSeq" :class="wordResultOk ? 'ok' : 'fail'">
        {{ wordResultText || '尚未生成。' }}
      </p>
    </el-card>
  </div>
</template>

<style>
body {
  margin: 0;
  background: #f5f7fa;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
.d0-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}
.d0-page h1 {
  font-size: 20px;
}
.block {
  margin-top: 16px;
}
.actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 12px;
}
.ok {
  color: #1f7a34;
}
.fail {
  color: #b42318;
}
.muted {
  color: #667085;
  font-size: 12px;
}
</style>
