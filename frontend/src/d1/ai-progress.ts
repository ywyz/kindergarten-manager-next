import type { AiTaskProgress } from './types'

/** Read-only task progress shared by daily, listening and weekly AI panels. */
export type AiProgressView = AiTaskProgress & { receivedAt: number }

const TERMINAL_PHASES = new Set([
  'completed',
  'failed',
  'unknown',
  'cancelled',
  'paused',
])

export const AI_PROGRESS_PHASE_LABELS: Record<string, string> = {
  waiting: '等待服务响应',
  thinking: '正在思考',
  generating: '正在生成结果',
  validating: '正在校验结果',
  completed: '已收到结果',
  failed: '已失败',
  unknown: '结果不明',
  paused: '已暂停',
  cancelled: '已取消',
  retry_wait: '等待安全重试',
  unavailable: '暂无进度',
}

export function isTerminalProgressPhase(phase: string): boolean {
  return TERMINAL_PHASES.has(phase)
}

export function progressPhaseLabel(phase: string): string {
  return AI_PROGRESS_PHASE_LABELS[phase] ?? '处理中'
}

/**
 * A progress snapshot belongs to the current task execution only. A late read
 * from an older execution/attempt is ignored rather than shown as current.
 */
export function progressMatchesTask(
  taskId: string,
  executionId: string | null,
  attemptNo: number | null,
  progress: AiTaskProgress,
): boolean {
  if (progress.task_id !== taskId) return false
  if (progress.execution_id !== executionId) return false
  return (
    attemptNo === null ||
    progress.attempt_no === null ||
    progress.attempt_no === attemptNo
  )
}

export function acceptedProgress(
  taskId: string,
  executionId: string | null,
  attemptNo: number | null,
  progress: AiTaskProgress,
): AiProgressView | null {
  if (!progressMatchesTask(taskId, executionId, attemptNo, progress)) return null
  return { ...progress, receivedAt: Date.now() }
}

export function progressElapsedSeconds(
  progress: AiProgressView,
  now = Date.now(),
): number {
  const local = isTerminalProgressPhase(progress.phase)
    ? 0
    : Math.max(0, now - progress.receivedAt)
  return Math.max(0, Math.floor((progress.elapsed_ms + local) / 1000))
}

export function progressLastDataSeconds(
  progress: AiProgressView,
  now = Date.now(),
): number | null {
  if (progress.last_data_age_ms === null) return null
  const local = isTerminalProgressPhase(progress.phase)
    ? 0
    : Math.max(0, now - progress.receivedAt)
  return Math.max(
    0,
    Math.floor((progress.last_data_age_ms + local) / 1000),
  )
}
