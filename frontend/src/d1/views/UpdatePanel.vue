<script setup lang="ts">
/**
 * D3-U update panel: discovery, download/verification and the explicit U2
 * install confirmation. Installation itself runs only after the reviewed
 * close handshake; the page never supplies a path, URL, PID or command.
 */
import { computed, ref } from 'vue'
import {
  canCancelUpdate,
  canCheckUpdate,
  canDownloadUpdate,
  canInstallUpdate,
  canRetryUpdate,
  formatBytes,
  isUpdateBusy,
  updateErrorText,
  updateProgressText,
  updateStateLabel,
  type UpdateStatus,
} from '../update'

const props = defineProps<{
  open: boolean
  status: UpdateStatus | null
  frozen?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'check'): void
  (e: 'download'): void
  (e: 'cancel'): void
  (e: 'retry'): void
  (e: 'install'): void
}>()

const busy = computed(() => isUpdateBusy(props.status))
const currentVersion = computed(() => props.status?.current?.version ?? '—')
const target = computed(() => props.status?.target)
const stateLabel = computed(() => updateStateLabel(props.status))
const errorText = computed(() => updateErrorText(props.status))
const progressText = computed(() => updateProgressText(props.status))
const progressPercent = computed(() => props.status?.progress.percent ?? 0)
const showError = computed(() => props.status?.state === 'failed')
const showNoRelease = computed(() => props.status?.state === 'no_release')
const downloadUnavailable = computed(
  () =>
    props.status?.state === 'available' &&
    props.status?.target != null &&
    props.status?.download_available === false,
)
const unavailableTitle = computed(() => {
  if (props.status?.allow_install === false) {
    return '当前为源码运行：只能检查 GitHub 版本，不能下载或安装替换'
  }
  if (props.status?.error_code === 'UPDATE_ASSETS_MISSING') {
    return '发现新版，但该 Release 缺少固定更新清单或完整包'
  }
  if (props.status?.error_code === 'UPDATE_TRUST_UNCONFIGURED') {
    return '发现新版，但尚未配置发行公钥'
  }
  return '发现新版，但当前暂不可安全下载'
})
const showUnconfigured = computed(
  () => props.status?.state === 'unconfigured' || props.status?.state === 'disabled',
)
const installAvailable = computed(
  () => !props.frozen && canInstallUpdate(props.status),
)
const confirmInstallOpen = ref(false)

function close(): void {
  emit('update:open', false)
}

function requestInstall(): void {
  if (installAvailable.value) confirmInstallOpen.value = true
}

function confirmInstall(): void {
  confirmInstallOpen.value = false
  emit('install')
}

function onDialogValue(value: boolean): void {
  if (!value) close()
  else emit('update:open', true)
}
</script>

<template>
  <el-dialog
    :model-value="open"
    title="应用更新"
    width="620px"
    :close-on-click-modal="false"
    data-d1="update-panel"
    @update:model-value="onDialogValue"
  >
    <div class="update-head">
      <span>当前版本：<strong>v{{ currentVersion }}</strong></span>
      <el-tag size="small" type="info">{{ stateLabel }}</el-tag>
    </div>

    <el-alert
      v-if="showUnconfigured"
      type="info"
      :closable="false"
      class="section"
      data-d1="update-unconfigured"
      :title="props.status?.reason === 'UPDATE_DISABLED_SOURCE_RUN'
        ? '当前为源码运行，未启用产品更新；不影响日计划手工使用。'
        : '更新渠道尚未配置；不会联网猜测地址，也不影响日计划手工使用。'"
    />

    <template v-if="target">
      <div class="release-meta" data-d1="update-target">
        <p><strong>新版本：v{{ target.version }}</strong></p>
        <p v-if="target.build_id" class="muted">构建 {{ target.build_id }} · 平台 {{ target.platform }}/{{ target.arch }}</p>
        <p v-if="target.package_size" class="muted">包大小：{{ formatBytes(target.package_size) }}</p>
      </div>
      <div class="release-notes">
        <h4>更新说明</h4>
        <pre data-d1="update-release-notes">{{ target.release_notes || '（无说明）' }}</pre>
      </div>
    </template>

    <div v-if="busy || props.status?.state === 'downloading'" class="section" data-d1="update-progress">
      <p>{{ progressText }}</p>
      <el-progress
        :percentage="progressPercent"
        :status="props.status?.state === 'failed' ? 'exception' : undefined"
      />
    </div>

    <el-alert
      v-if="props.status?.state === 'ready'"
      type="success"
      :closable="false"
      class="section"
      data-d1="update-ready"
      title="完整包已下载并通过校验"
    >
      <p>
        安装会先保存并关闭当前应用，旧进程退出后才切换程序目录，再用原数据根和凭据根启动新版。
        当前程序和数据尚未改动。
      </p>
    </el-alert>

    <el-alert
      v-if="showError"
      type="error"
      :closable="false"
      class="section"
      data-d1="update-error"
      :title="errorText"
    />

    <el-alert
      v-if="props.status?.state === 'cancelled'"
      type="warning"
      :closable="false"
      class="section"
      data-d1="update-cancelled"
      title="下载已取消；未进入可安装状态"
    />

    <el-alert
      v-if="props.status?.state === 'up_to_date'"
      type="info"
      :closable="false"
      class="section"
      data-d1="update-up-to-date"
      title="当前已是最新版本"
    />

    <el-alert
      v-if="showNoRelease"
      type="info"
      :closable="false"
      class="section"
      data-d1="update-no-release"
      title="GitHub 尚无正式 Release；不影响本地使用"
    />

    <el-alert
      v-if="downloadUnavailable"
      type="warning"
      :closable="false"
      class="section"
      data-d1="update-unavailable"
      :title="unavailableTitle"
    />

    <template #footer>
      <div class="footer">
        <el-button
          data-d1="update-check"
          :disabled="props.frozen || !canCheckUpdate(props.status)"
          :loading="props.status?.state === 'checking'"
          @click="emit('check')"
        >
          检查更新
        </el-button>
        <el-button
          v-if="canDownloadUpdate(props.status)"
          type="primary"
          data-d1="update-download"
          :disabled="props.frozen"
          @click="emit('download')"
        >
          下载更新
        </el-button>
        <el-button
          v-if="canCancelUpdate(props.status)"
          data-d1="update-cancel"
          :disabled="props.frozen"
          @click="emit('cancel')"
        >
          取消下载
        </el-button>
        <el-button
          v-if="canRetryUpdate(props.status)"
          data-d1="update-retry"
          :disabled="props.frozen"
          @click="emit('retry')"
        >
          重试
        </el-button>
        <el-button
          v-if="installAvailable"
          type="primary"
          data-d1="update-install"
          :disabled="props.frozen"
          @click="requestInstall"
        >
          安装并重启
        </el-button>
        <el-button data-d1="update-close" @click="close">关闭</el-button>
      </div>
    </template>
  </el-dialog>

  <el-dialog
    v-model="confirmInstallOpen"
    title="确认安装更新"
    width="480px"
    :close-on-click-modal="false"
    data-d1="update-install-confirm"
  >
    <p>安装前会保存当前内容并关闭应用。确定现在安装并重启吗？</p>
    <template #footer>
      <el-button data-d1="update-install-cancel" @click="confirmInstallOpen = false">
        取消
      </el-button>
      <el-button type="primary" data-d1="update-install-confirm-button" @click="confirmInstall">
        确认安装并重启
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.update-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.release-meta p {
  margin: 4px 0;
}
.release-notes {
  margin-top: 12px;
}
.release-notes pre {
  margin: 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow: auto;
  font-size: 0.85rem;
}
.section {
  margin-top: 12px;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
