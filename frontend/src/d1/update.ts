/** D3-U U1 update discovery/download state (no install action). */

export interface AppIdentity {
  app_id: string
  app_name: string
  channel: string
  version: string
  build_id: string
  package_format: string
  platform: string
  arch: string
  python: string
  database_revision: string
}

export type UpdateState =
  | 'disabled'
  | 'unconfigured'
  | 'idle'
  | 'checking'
  | 'up_to_date'
  | 'no_release'
  | 'available'
  | 'downloading'
  | 'verifying'
  | 'ready'
  | 'cancelled'
  | 'closed'
  | 'failed'

export interface UpdateTarget {
  app_id: string
  channel: string
  version: string
  build_id: string
  platform: string
  arch: string
  package_format: string
  package_size: number
  database_revision: string
  release_notes: string
  published_at: string
}

export interface UpdateProgress {
  downloaded: number
  total: number
  percent: number
}

export interface UpdateStatus {
  state: UpdateState
  reason: string | null
  current: AppIdentity | null
  target: UpdateTarget | null
  progress: UpdateProgress
  release_notes: string
  error_code: string | null
  error_message: string | null
  /** True only when the host has a verified package ready to install. */
  install_available: boolean
  download_available?: boolean
  allow_install?: boolean
  install_state?: string
  install_plan_id?: string | null
  install_reason?: string | null
  install_result?: {
    status?: string
    code?: string | null
  } | null
  download_id: string | null
}

export const EMPTY_UPDATE_STATUS: UpdateStatus = {
  state: 'idle',
  reason: null,
  current: null,
  target: null,
  progress: { downloaded: 0, total: 0, percent: 0 },
  release_notes: '',
  error_code: null,
  error_message: null,
  install_available: false,
  download_id: null,
}

export function updateStateLabel(status: UpdateStatus | null): string {
  switch (status?.state) {
    case 'disabled':
      return '当前源码运行未启用应用更新'
    case 'unconfigured':
      return '更新渠道尚未配置'
    case 'checking':
      return '正在检查更新…'
    case 'up_to_date':
      return '当前已是最新版本'
    case 'no_release':
      return '尚无正式 Release'
    case 'available':
      return '发现新版本'
    case 'downloading':
      return '正在下载更新…'
    case 'verifying':
      return '正在校验完整包…'
    case 'ready':
      return '已下载并校验完成'
    case 'cancelled':
      return '下载已取消'
    case 'closed':
      return '更新已关闭'
    case 'failed':
      return '更新检查或下载失败'
    default:
      return '尚未检查更新'
  }
}

export function isUpdateBusy(status: UpdateStatus | null): boolean {
  return ['checking', 'downloading', 'verifying'].includes(status?.state ?? '')
}

export function canCheckUpdate(status: UpdateStatus | null): boolean {
  return !isUpdateBusy(status)
}

export function canDownloadUpdate(status: UpdateStatus | null): boolean {
  return status?.state === 'available' && status.download_available !== false
}

export function canCancelUpdate(status: UpdateStatus | null): boolean {
  return status?.state === 'downloading'
}

export function canRetryUpdate(status: UpdateStatus | null): boolean {
  return status?.state === 'failed' || status?.state === 'cancelled'
}

export function canInstallUpdate(status: UpdateStatus | null): boolean {
  return status?.state === 'ready' && status.install_available === true
}

export function updateProgressText(status: UpdateStatus | null): string {
  const progress = status?.progress
  if (!progress || progress.total <= 0) return '正在准备…'
  return `已下载 ${formatBytes(progress.downloaded)} / ${formatBytes(progress.total)}（${progress.percent}%）`
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export function updateErrorText(status: UpdateStatus | null): string {
  if (status?.error_message) return status.error_message
  switch (status?.error_code) {
    case 'UPDATE_CHANNEL_UNCONFIGURED':
      return '更新渠道尚未配置；不影响当前手工使用'
    case 'UPDATE_CONFIG_INVALID':
      return '更新发行配置无效；未联网检查'
    case 'UPDATE_NO_RELEASE':
      return 'GitHub 尚无正式 Release；不影响本地使用'
    case 'UPDATE_RATE_LIMITED':
      return 'GitHub API 限流或暂时拒绝请求；请稍后重试'
    case 'UPDATE_ASSETS_MISSING':
      return '发现新版，但该 Release 缺少固定更新清单或完整包；暂不可下载'
    case 'UPDATE_TRUST_UNCONFIGURED':
      return '发现新版，但尚未配置发行公钥；暂不可安全下载'
    case 'UPDATE_TRUST_CONFIG_WRITE':
      return '无法写入更新器信任配置；暂不可安装'
    case 'UPDATE_METADATA_UNTRUSTED':
      return '发行信息签名不可验证；未下载'
    case 'UPDATE_METADATA_INVALID':
      return '发行信息不完整或版本不兼容；未下载'
    case 'UPDATE_PACKAGE_MISMATCH':
      return '下载包大小或摘要与发行信息不符；未进入可安装状态'
    case 'UPDATE_PACKAGE_INVALID':
      return '下载包结构或清单不合法；未进入可安装状态'
    case 'UPDATE_STAGING_UNSAFE':
      return '更新暂存路径包含链接或重解析点；已拒绝写入'
    case 'UPDATE_STAGING_UNAVAILABLE':
      return '更新暂存目录不可用；已拒绝下载'
    case 'UPDATE_STAGING_OVERLAP':
      return '更新暂存目录与数据或凭据目录重叠；已拒绝下载'
    case 'UPDATE_DOWNLOAD_TIMEOUT':
      return '下载读取超时；未进入可安装状态'
    case 'UPDATE_CANCELLED':
      return '下载已取消'
    default:
      return '更新检查或下载失败，请稍后重试'
  }
}
