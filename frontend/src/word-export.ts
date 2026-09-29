/**
 * I5 Word export (slice 3) shared view helpers: error wording per spec §8,
 * success-path warnings surfaced from the `X-Export-Warnings` header, and
 * the one-shot blob download (temporary object URL + `<a download>`, revoked
 * immediately after the click; file bytes never enter app state, logs or
 * localStorage).
 */

import type { ApiError, ExportError } from './api'
import type { ExportDownloadResult, ExportWarning } from './types'

export const EXPORT_LIMIT_DAILY = 31
export const EXPORT_LIMIT_WEEKLY = 8

export function isExportError(err: unknown): err is ExportError {
  if (typeof err !== 'object' || err === null) return false
  return 'status' in err && 'code' in err
}

/** Exact Chinese wording per slice-3 error code (views may add counts). */
export function exportWordErrorMessage(err: unknown, fallback: string): string {
  if (!isExportError(err)) return fallback
  const api = err as ExportError
  switch (api.code) {
    case 'AUTH_REQUIRED':
      return '请先登录后再导出'
    case 'FORBIDDEN':
      return '没有导出该班级计划的权限'
    case 'WEEKLY_PLAN_NOT_FOUND':
      return '周计划不存在或已被删除'
    case 'CONFIRMATION_NOT_FOUND':
      return '该周计划还没有可导出的已确认版本'
    case 'EXPORT_NO_MATCH':
      return '所选范围内没有可导出的计划'
    case 'VALIDATION_ERROR':
      return '导出设置或日期范围不正确，请检查后重试'
    case 'EXPORT_RANGE_TOO_LARGE': {
      const limit = api.limit ?? (api as { limit?: number }).limit
      if (limit) {
        return `导出范围过大：一次最多导出 ${limit} 份，请缩小日期范围`
      }
      return '导出范围过大，请缩小日期范围'
    }
    case 'EXPORT_ACK_REQUIRED':
      return '范围内存在内容缺项，需要确认后才能导出'
    case 'EXPORT_UNAVAILABLE':
      return '导出服务暂不可用（模板资产异常），请稍后重试'
    case 'SERVICE_UNAVAILABLE':
      return '导出依赖的持久化服务暂不可用，请稍后重试'
    case 'EXPORT_FAILED':
      return 'Word 文件生成失败，请稍后重试'
    default: {
      return `导出失败：${(api as ApiError).message || api.code || fallback}`
    }
  }
}

/** Human text for one confirmed_not_latest reason (from the response header). */
function weeklyWarningReasonText(reason: string): string {
  switch (reason) {
    case 'draft_ahead':
      return '确认后已产生新的草稿'
    case 'stale_sources':
      return '来源日计划已有更新'
    case 'superseded':
      return '已存在更新的确认版本'
    case 'recorded_stale':
      return '确认时已记录未更新的来源'
    default:
      return reason
  }
}

/** Success-text lines derived only from the actual response warnings. */
export function exportWarningTexts(warnings: ExportWarning[]): string[] {
  const lines: string[] = []
  if (warnings.some((w) => w.code === 'no_split_baseline')) {
    lines.push('部分日计划没有拆分基准，已按最终内容导出且未标红')
  }
  const notLatest = warnings.filter(
    (w) => w.code === 'confirmed_not_latest',
  )
  if (notLatest.length > 0) {
    const reasons = notLatest
      .map((w) => (w.reason ? weeklyWarningReasonText(w.reason) : ''))
      .filter(Boolean)
    if (reasons.length > 0) {
      lines.push(
        `导出的是已确认版本，但未包含最新变化（${Array.from(new Set(reasons)).join('；')}）`,
      )
    } else {
      lines.push('导出的是已确认版本，但未包含最新变化')
    }
  }
  return lines
}

/** One-time blob download; revoked immediately after the click. */
export function triggerExportDownload(
  result: ExportDownloadResult,
  fallbackName: string,
): void {
  const blob = result.blob
  const filename = result.filename || fallbackName
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
