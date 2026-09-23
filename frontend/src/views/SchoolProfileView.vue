<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElButton, ElCard, ElInput, ElMessage } from 'element-plus'
import type { ConfigurationChange } from '../types'
import * as api from '../api'
import { handleApiError } from '../auth'
import PreviewDialog from '../components/PreviewDialog.vue'
import {
  clearPending,
  getPending,
  rememberPending,
  restorePending,
} from '../composables/usePendingChange'

const schoolName = ref('')
const version = ref(1)
const loading = ref(false)
const submitting = ref(false)
const previewOpen = ref(false)

const pendingPreview = computed<ConfigurationChange | null>(() => {
  const p = getPending()
  if (p && p.kind === 'school_update') return p
  return null
})

const stale = ref(false)
const staleMessage = ref('')
const latestVersion = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const settings = await api.getSchoolSettings()
    schoolName.value = settings.school_name || ''
    version.value = settings.version
  } catch (err) {
    handleApiError(err, '加载园所资料失败')
  } finally {
    loading.value = false
  }
}

async function loadLatestVersion() {
  const settings = await api.getSchoolSettings()
  latestVersion.value = settings.version
  return settings.version
}

function restoreFormFromCandidate(change: ConfigurationChange) {
  const candidate = change.candidate
  if (candidate && typeof candidate.school_name === 'string') {
    schoolName.value = candidate.school_name
  }
  if (candidate && typeof candidate.expected_version === 'number') {
    version.value = candidate.expected_version
  }
}

async function init() {
  try {
    const outcome = await restorePending()
    if (outcome?.outcome === 'recovered' && outcome.change.kind === 'school_update') {
      restoreFormFromCandidate(outcome.change)
      latestVersion.value = null
      previewOpen.value = true
      return
    }
  } catch (err) {
    handleApiError(err, '恢复待处理预览失败')
  }
  await load()
}

async function submit() {
  stale.value = false
  staleMessage.value = ''
  submitting.value = true
  try {
    const expectedVersion = latestVersion.value ?? version.value
    const change = await api.createPreview({
      kind: 'school_update',
      school_name: schoolName.value.trim() || null,
      expected_version: expectedVersion,
    })
    rememberPending(change)
    previewOpen.value = true
    latestVersion.value = null
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'NO_CHANGES') {
      ElMessage.info('园所名称没有变更')
      return
    }
    if (e.status === 409) {
      try {
        await loadLatestVersion()
      } catch {
        // keep stale state
      }
      stale.value = true
      staleMessage.value =
        e.code === 'PREVIEW_EXPIRED'
          ? '预览已过期，可在核对最新版本后重新预览'
          : '数据版本已变化；下方为最新版本，输入已保留，请核对后重新预览'
      previewOpen.value = false
      return
    }
    handleApiError(err, '保存失败')
  } finally {
    submitting.value = false
  }
}

async function onApplied() {
  stale.value = false
  latestVersion.value = null
  previewOpen.value = false
  clearPending()
  await load()
}

async function onStale() {
  // Do not call load(): the user's candidate input must stay in the form.
  // Refresh the latest server version so the next re-preview uses it.
  try {
    await loadLatestVersion()
  } catch {
    // keep stale state
  }
  stale.value = true
  staleMessage.value = '数据版本已变化；输入已保留，请核对后重新预览'
  previewOpen.value = false
}

function onRePreview() {
  previewOpen.value = false
  submit()
}

function onPreviewClosed() {
  previewOpen.value = false
  // Closing the dialog does not discard the form input. The pending pointer
  // is intentionally kept so a refresh can recover the candidate; it is only
  // cleared after a successful apply or when the user explicitly cancels the
  // whole operation (handled by applied above).
}

onMounted(init)
</script>

<template>
  <el-card v-loading="loading">
    <h3>园所资料</h3>
    <div class="field">
      <label>园所名称</label>
      <el-input v-model="schoolName" maxlength="120" show-word-limit placeholder="未填写" />
    </div>
    <div v-if="stale" class="stale">
      <p>{{ staleMessage }}</p>
      <p v-if="latestVersion !== null">最新版本：{{ latestVersion }}</p>
    </div>
    <el-button type="primary" :loading="submitting" @click="submit">
      {{ stale ? '核对后重新预览' : '下一步：预览' }}
    </el-button>
  </el-card>

  <PreviewDialog
    v-model="previewOpen"
    :change="pendingPreview"
    @applied="onApplied"
    @stale="onStale"
    @re-preview="onRePreview"
    @update:model-value="(v) => { if (!v) onPreviewClosed() }"
  />
</template>

<style scoped>
.field { margin: 16px 0; max-width: 420px; }
.field label { display: block; margin-bottom: 6px; color: #606266; }
.stale {
  margin: 12px 0;
  padding: 8px 12px;
  background: #fdf6ec;
  border-radius: 4px;
  color: #b88230;
  font-size: 0.875rem;
  max-width: 420px;
}
</style>
