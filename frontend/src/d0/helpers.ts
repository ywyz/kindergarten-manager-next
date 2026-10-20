/**
 * D0 window helpers exposed as ``window.__d0`` for the automated driver and
 * used by the page itself. They wrap: pywebview session retrieval, guarded
 * API calls, the REAL save/export button flows (Element Plus click path), and
 * the restricted host save. The token never touches the URL.
 */

import { apiGet, setSessionToken, type ApiResult } from './client'
import {
  isSaveApiReady,
  isSessionApiReady,
  waitForSessionApi,
  type PywebviewGlobal,
} from './bridge'

export interface ProbeState {
  status: string
  content?: string | null
  version?: number | null
  updated_at?: string | null
}

export interface EnvironmentInfo {
  python_version?: string
  frozen?: boolean
  webview2_runtime_version?: string | null
  frontend_dir?: string
  sqlite_library_version?: string
  sqlite_runtime_version?: string
  pysqlite_module_version?: string
  dialect?: string
  driver?: string
  foreign_keys_pragma?: number
  journal_mode?: string
  transaction_style?: string
  write_then_verify_before_commit?: boolean
  data_dir?: string
  db_path?: string
}

export interface UiSaveResult {
  messageVisible: boolean
  failureMessageVisible: boolean
  messageText: string
  checkboxNow: boolean | null
  inputContent: string
  seq: number | null
}

export interface WordExportResult {
  status: string
  path?: string
  message?: string
}

interface D0Bridge {
  collectSession: () => Promise<{ hasToken?: boolean }>
  getStateNoHeader: () => Promise<unknown>
  getStateWithHeader: () => Promise<ProbeState>
  getHealth: () => Promise<unknown>
  getInputContent: () => string
  triggerUiSave: (options?: {
    simulateFailure?: boolean
    content?: string
  }) => Promise<UiSaveResult>
  triggerWordExport: () => Promise<WordExportResult>
  triggerWordExportAutosave: (target: string) => Promise<WordExportResult>
}

let hostSaveDefaultFilename = 'D0验证_日计划.docx'

export function setHostSaveDefaultFilename(name: string): void {
  hostSaveDefaultFilename = name
}

function hostGlobal(): PywebviewGlobal | undefined {
  return (window as unknown as { pywebview?: PywebviewGlobal }).pywebview
}

export function waitForHostSession(): Promise<'ready' | 'timeout'> {
  return waitForSessionApi(() => hostGlobal())
}

export async function collectSession(): Promise<{ hasToken?: boolean }> {
  const host = hostGlobal()
  if (!isSessionApiReady(host)) return {}
  const session = await host!.api!.get_session!()
  const token = session?.launch_token
  if (!token) return {}
  setSessionToken(token)
  return { hasToken: true }
}

export function getStateNoHeader(): Promise<unknown> {
  return apiGet<ProbeState>('/api/probe/state', false)
}

export function getStateWithHeader(): Promise<ProbeState> {
  return apiGet<ProbeState>('/api/probe/state', true).then(handleApiResult)
}

export function getHealth(): Promise<unknown> {
  return fetch('/api/probe/health')
    .then((response) => response.json())
    .catch(() => ({ status: 'error' }))
}

async function handleApiResult<T>(
  result: ApiResult<T>,
): Promise<T | { status: 'failed'; message: string }> {
  if (result.ok) return result.data
  return { status: 'failed', message: result.message }
}

function readSeq(selector: string, attribute: string): number | null {
  const host = document.querySelector<HTMLElement>(selector)
  const raw = host?.getAttribute(attribute)
  return raw === null || raw === undefined || raw === '' ? null : Number(raw)
}

function readTextarea(): string {
  const host = document.querySelector<HTMLElement>('[data-d0="probe-content"]')
  const textarea =
    host instanceof HTMLTextAreaElement
      ? host
      : host?.querySelector('textarea') ?? null
  return textarea?.value ?? ''
}

export function getInputContent(): string {
  return readTextarea()
}

async function setCheckbox(
  failureCheckbox: HTMLElement | null,
  want: boolean,
): Promise<void> {
  if (!failureCheckbox) return
  const input = failureCheckbox.querySelector<HTMLInputElement>('input')
  if (!input) return
  if (input.checked !== want) {
    // Click the Element Plus checkbox root (a <label>) to toggle it.
    failureCheckbox.click()
  }
  const deadline = Date.now() + 2000
  while (Date.now() < deadline && input.checked !== want) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
}

export async function triggerUiSave(
  options: { simulateFailure?: boolean; content?: string } = {},
): Promise<UiSaveResult> {
  const result: UiSaveResult = {
    messageVisible: false,
    failureMessageVisible: false,
    messageText: '',
    checkboxNow: null,
    inputContent: '',
    seq: null,
  }
  const saveButton = document.querySelector<HTMLButtonElement>('[data-d0="save-state"]')
  if (!saveButton) return result
  const textareaHost = document.querySelector<HTMLElement>('[data-d0="probe-content"]')
  const textarea =
    textareaHost instanceof HTMLTextAreaElement
      ? textareaHost
      : textareaHost?.querySelector('textarea') ?? null
  if (textarea && options.content !== undefined) {
    textarea.value = options.content
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  }
  const failureCheckbox = document.querySelector<HTMLElement>('[data-d0="simulate-failure"]')
  await setCheckbox(failureCheckbox, options.simulateFailure ?? false)
  const beforeSeq = readSeq('[data-d0="save-result"]', 'data-d0-seq')
  saveButton.click()
  // Wait for the page's own save counter to advance instead of a fixed sleep.
  const deadline = Date.now() + 20000
  while (Date.now() < deadline) {
    const now = readSeq('[data-d0="save-result"]', 'data-d0-seq')
    if (now !== null && now !== beforeSeq) break
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  const messageHost = document.querySelector<HTMLElement>('[data-d0="save-result"]')
  const text = messageHost?.textContent ?? ''
  const checkboxInput = failureCheckbox?.querySelector<HTMLInputElement>('input') ?? null
  return {
    messageVisible: text.includes('保存成功'),
    failureMessageVisible: text.includes('保存失败'),
    messageText: text,
    checkboxNow: checkboxInput?.checked ?? null,
    inputContent: readTextarea(),
    seq: readSeq('[data-d0="save-result"]', 'data-d0-seq'),
  }
}

function readWordResult(): WordExportResult | undefined {
  return (
    window as unknown as { __d0WordResult?: WordExportResult }
  ).__d0WordResult
}

export async function triggerWordExport(
  timeoutMs = 60000,
): Promise<WordExportResult> {
  const exportButton = document.querySelector<HTMLButtonElement>('[data-d0="save-word"]')
  if (!exportButton) return { status: 'failed', message: '未找到保存按钮' }
  const beforeSeq = readSeq('[data-d0="word-result"]', 'data-d0-word-seq')
  exportButton.click()
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const now = readSeq('[data-d0="word-result"]', 'data-d0-word-seq')
    if (now !== null && now !== beforeSeq) {
      const result = readWordResult()
      if (result) return result
      break
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  return { status: 'timeout', message: '导出未在时限内结束' }
}

export async function triggerWordExportAutosave(
  target: string,
): Promise<WordExportResult> {
  // Verification-only hook: the page still runs its real export function and
  // its /api call; the host save is directed to the pre-authorized dir.
  ;(window as unknown as Record<string, unknown>).__d0AutosaveTarget = target
  try {
    return await triggerWordExport()
  } finally {
    delete (window as unknown as Record<string, unknown>).__d0AutosaveTarget
  }
}

export { isSaveApiReady }

export function initD0Helpers(): void {
  ;(window as unknown as { __d0?: D0Bridge }).__d0 = {
    collectSession,
    getStateNoHeader,
    getStateWithHeader,
    getHealth,
    getInputContent,
    triggerUiSave,
    triggerWordExport,
    triggerWordExportAutosave,
  }
}
