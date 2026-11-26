/**
 * Optional Nextcloud Tasks (CalDAV) todo sync client and page store.
 *
 * The linkage is off by default and only turns on when the teacher
 * explicitly chooses 「双向同步所选清单（新增、编辑和完成）」.  The
 * Nextcloud password is sent once to the local API over the same-origin
 * session and then lives only in the machine-local DPAPI store: it is never
 * returned by any endpoint, never persisted in the frontend and never
 * written into the local database or a backup package.
 */

import { computed, reactive, ref } from 'vue'
import { apiGet, apiPost, ApiError } from './client'

const SYNC_ROOT = '/api/local/todos/nextcloud'

export interface TodoSyncCredentialView {
  configured: boolean
  url?: string
  username?: string
  password_available?: boolean
  reason?: string
  detail?: string
}

export interface TodoSyncSettingView {
  configured: boolean
  enabled: boolean
  server_url?: string
  username?: string
  list_href?: string | null
  list_name?: string | null
  setting_version: number
  last_sync_at?: string | null
  last_result?: Record<string, unknown> | null
}

export interface TodoSyncStatusView {
  setting: TodoSyncSettingView
  credential: TodoSyncCredentialView
}

export interface TodoSyncListView {
  href: string
  display_name: string
  supports_vtodo: boolean
}

export interface TodoSyncListsView {
  lists: TodoSyncListView[]
  selected: string | null
  enabled: boolean
}

export interface TodoSyncResultView {
  state?: string
  pulled_created?: number
  pulled_updated?: number
  pushed_created?: number
  pushed_updated?: number
  reattached?: number
  remote_missing?: number
  conflicts?: number
  remote_kept_local?: number
  error_codes?: string[]
}

export interface TodoSyncApi {
  status(): Promise<TodoSyncStatusView>
  connect(input: {
    request_id: string
    url: string
    username: string
    password: string
  }): Promise<{
    ok: boolean
    enabled: boolean
    server_url: string
    username: string
    setting_version: number
  }>
  lists(): Promise<TodoSyncListsView>
  select(input: {
    request_id: string
    expected_version: number
    list_href: string
  }): Promise<{
    ok: boolean
    enabled: boolean
    list_href: string
    list_name: string
    setting_version: number
  }>
  sync(request_id: string): Promise<TodoSyncResultView>
  disable(input: {
    request_id: string
    expected_version: number
    clear_credentials: boolean
  }): Promise<{
    ok: boolean
    enabled: boolean
    setting_version: number
    credentials_cleared: boolean
  }>
}

export function createTodoSyncApi(): TodoSyncApi {
  return {
    status: () => apiGet<TodoSyncStatusView>(`${SYNC_ROOT}/status`),
    connect: (input) => apiPost(`${SYNC_ROOT}/connect`, input),
    lists: () => apiPost<TodoSyncListsView>(`${SYNC_ROOT}/lists`, {}),
    select: (input) => apiPost(`${SYNC_ROOT}/select`, input),
    sync: (requestId) =>
      apiPost<TodoSyncResultView>(`${SYNC_ROOT}/sync`, {
        request_id: requestId,
      }),
    disable: (input) => apiPost(`${SYNC_ROOT}/disable`, input),
  }
}

/** Fixed teacher-facing text for the fixed error codes. */
export function todoSyncErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'SYNC_AUTH_FAILED') return 'Nextcloud 用户名或密码不正确'
    if (error.code === 'SYNC_URL_NOT_HTTPS') return 'Nextcloud 地址必须使用 HTTPS'
    if (error.code === 'SYNC_URL_INVALID') return 'Nextcloud 地址格式不正确'
    if (error.code === 'SYNC_CREDENTIAL_UNAVAILABLE') {
      return '本机保存的 Nextcloud 密码不可用，请重新输入'
    }
    if (error.code === 'SYNC_CREDENTIAL_ACCOUNT_MISMATCH') {
      return '本机保存的密码属于其他 Nextcloud 账户，请重新连接本档案要用的账户'
    }
    if (error.code === 'SYNC_LIST_UNSUPPORTED') {
      return '所选清单不支持任务（VTODO），请选择支持任务的清单'
    }
    if (error.code === 'SYNC_LIST_TRUNCATED') {
      return '任务清单数量超过同步上限，已停止同步以避免误判删除'
    }
    if (error.code === 'SYNC_VERSION_CONFLICT') return '同步设置已在其他窗口更新，请刷新后重试'
    if (error.code === 'SYNC_REQUEST_CONFLICT') return '该请求已用于不同内容，请重新发起'
    if (error.code === 'SYNC_LIST_NOT_FOUND') return '所选清单不存在，请刷新后重新选择'
    if (error.code === 'SYNC_PRECONDITION_FAILED') return '远端任务已被其他设备修改，未覆盖'
    if (error.status === 0) return '本地服务未响应，请稍后重试'
    return error.message || 'Nextcloud 同步操作失败，请稍后重试'
  }
  return 'Nextcloud 同步操作失败，请稍后重试'
}

export function todoSyncResultText(result: TodoSyncResultView): string {
  if (result.state === 'disabled') return '双向同步未开启'
  const parts: string[] = []
  if (result.pulled_created) parts.push(`从远端新增 ${result.pulled_created} 项`)
  if (result.pulled_updated) parts.push(`远端更新 ${result.pulled_updated} 项`)
  if (result.pushed_created) parts.push(`已上传新增 ${result.pushed_created} 项`)
  if (result.pushed_updated) parts.push(`已上传修改 ${result.pushed_updated} 项`)
  if (result.reattached) parts.push(`重新关联 ${result.reattached} 项`)
  if (result.conflicts) parts.push(`双方都修改 ${result.conflicts} 项（未覆盖）`)
  if (result.remote_missing) parts.push(`远端已删除 ${result.remote_missing} 项（本地保留）`)
  if (!parts.length) return '本次同步没有变化'
  return `同步完成：${parts.join('，')}`
}

export function createTodoSyncStore(api: TodoSyncApi = createTodoSyncApi()) {
  const state = reactive({
    status: null as TodoSyncStatusView | null,
    lists: [] as TodoSyncListView[],
    selectedHref: '',
    loading: false,
    connecting: false,
    selecting: false,
    syncing: false,
    error: '',
    notice: '',
    lastResult: null as TodoSyncResultView | null,
  })
  const enabled = computed(
    () => state.status?.setting.enabled === true,
  )
  const connected = computed(
    () => state.status?.setting.configured === true,
  )
  const credentialReady = computed(
    () => state.status?.credential.password_available === true,
  )

  async function loadStatus(): Promise<void> {
    state.error = ''
    try {
      state.status = await api.status()
    } catch (error) {
      state.error = todoSyncErrorText(error)
    }
  }

  async function connect(input: {
    url: string
    username: string
    password: string
  }): Promise<boolean> {
    if (state.connecting) return false
    state.connecting = true
    state.error = ''
    state.notice = ''
    try {
      await api.connect({ request_id: crypto.randomUUID(), ...input })
      await loadStatus()
      state.notice = '已连接 Nextcloud；请选择要联动的清单'
      return true
    } catch (error) {
      state.error = todoSyncErrorText(error)
      return false
    } finally {
      state.connecting = false
    }
  }

  async function loadLists(): Promise<void> {
    if (state.loading) return
    state.loading = true
    state.error = ''
    try {
      const view = await api.lists()
      state.lists = view.lists
      state.selectedHref = view.selected || ''
    } catch (error) {
      state.error = todoSyncErrorText(error)
    } finally {
      state.loading = false
    }
  }

  async function selectList(href: string): Promise<boolean> {
    const setting = state.status?.setting
    if (!setting || state.selecting) return false
    state.selecting = true
    state.error = ''
    state.notice = ''
    try {
      await api.select({
        request_id: crypto.randomUUID(),
        expected_version: setting.setting_version,
        list_href: href,
      })
      await loadStatus()
      state.notice = '已开启双向同步所选清单（新增、编辑和完成）'
      return true
    } catch (error) {
      state.error = todoSyncErrorText(error)
      await loadStatus()
      return false
    } finally {
      state.selecting = false
    }
  }

  async function syncNow(): Promise<boolean> {
    if (state.syncing || !enabled.value) return false
    state.syncing = true
    state.error = ''
    state.notice = ''
    try {
      const result = await api.sync(crypto.randomUUID())
      state.lastResult = result
      state.notice = todoSyncResultText(result)
      await loadStatus()
      return true
    } catch (error) {
      state.error = todoSyncErrorText(error)
      return false
    } finally {
      state.syncing = false
    }
  }

  async function disable(clearCredentials: boolean): Promise<boolean> {
    const setting = state.status?.setting
    if (!setting || state.syncing) return false
    state.error = ''
    state.notice = ''
    try {
      await api.disable({
        request_id: crypto.randomUUID(),
        expected_version: setting.setting_version,
        clear_credentials: clearCredentials === true,
      })
      await loadStatus()
      state.notice = clearCredentials
        ? '已停止联动并清除本机保存的 Nextcloud 密码'
        : '已停止联动；连接信息仍保留在本机'
      return true
    } catch (error) {
      state.error = todoSyncErrorText(error)
      await loadStatus()
      return false
    }
  }

  function resetLocal(): void {
    state.lists = []
    state.selectedHref = ''
    state.error = ''
    state.notice = ''
    state.lastResult = null
  }

  return {
    state,
    enabled,
    connected,
    credentialReady,
    loadStatus,
    connect,
    loadLists,
    selectList,
    syncNow,
    disable,
    resetLocal,
  }
}

export type TodoSyncStore = ReturnType<typeof createTodoSyncStore>

/** Module-level store shared by the settings panel and the workbench. */
const workbenchSyncStatus = ref<TodoSyncStatusView | null>(null)

export function rememberWorkbenchSyncStatus(status: TodoSyncStatusView): void {
  workbenchSyncStatus.value = status
}

export function workbenchSyncEnabled(): boolean {
  return workbenchSyncStatus.value?.setting.enabled === true
}

export function workbenchSyncLabel(): string {
  const setting = workbenchSyncStatus.value?.setting
  if (!setting || !setting.enabled) return ''
  const name = setting.list_name || '所选清单'
  const at = setting.last_sync_at ? `，上次同步 ${setting.last_sync_at}` : ''
  return `已与 Nextcloud「${name}」双向同步（新增、编辑和完成）${at}`
}
