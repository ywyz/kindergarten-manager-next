/**
 * Local personal todo client and page-lifetime store.
 *
 * Todos belong to the one local profile, never to a class or term.  The
 * module-level store keeps the draft and an unknown write across a quick
 * workbench switch; a component unmount does not abort or forget an
 * explicitly initiated write.
 */

import { computed, reactive } from 'vue'
import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  ApiError,
  pathSegment,
} from './client'

export interface LocalTodo {
  todo_id: string
  title: string
  due_date: string | null
  completed: boolean
  archived_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface TodoListPayload {
  items: LocalTodo[]
}

export interface TodoOperationResult {
  todo?: LocalTodo
  deleted?: boolean
  action?: 'archive' | 'delete'
  items?: LocalTodo[]
}

export interface TodoWritePending {
  requestId: string
  action: 'create' | 'update' | 'delete' | 'batch_archive' | 'batch_delete'
  todoId: string | null
  fields: Record<string, unknown>
  ownsDraft: boolean
  draftSession: number
}

export interface TodoUiError {
  code: string
  message: string
  unknown: boolean
  currentTodo?: LocalTodo
}

export interface TodoApi {
  list: (archived?: boolean) => Promise<TodoListPayload>
  create: (body: Record<string, unknown>) => Promise<LocalTodo>
  update: (todoId: string, body: Record<string, unknown>) => Promise<LocalTodo>
  remove: (todoId: string, body: Record<string, unknown>) => Promise<TodoOperationResult>
  batch: (body: Record<string, unknown>) => Promise<TodoOperationResult>
  operation: (requestId: string) => Promise<TodoOperationResult>
}

const TODO_ROOT = '/api/local/todos'

export function createTodoApi(): TodoApi {
  return {
    list: (archived = false) =>
      apiGet<TodoListPayload>(archived ? `${TODO_ROOT}?archived=true` : TODO_ROOT),
    create: (body) => apiPost<LocalTodo>(TODO_ROOT, body),
    update: (todoId, body) =>
      apiPatch<LocalTodo>(`${TODO_ROOT}/${pathSegment(todoId)}`, body),
    remove: (todoId, body) =>
      apiDelete<TodoOperationResult>(`${TODO_ROOT}/${pathSegment(todoId)}`, body),
    batch: (body) => apiPost<TodoOperationResult>(`${TODO_ROOT}/batch`, body),
    operation: (requestId) =>
      apiGet<TodoOperationResult>(
        `${TODO_ROOT}/operations/${pathSegment(requestId)}`,
      ),
  }
}

function errorCurrentTodo(error: ApiError): LocalTodo | undefined {
  const details = error.details
  if (!details || typeof details !== 'object') return undefined
  const candidate = (details as { todo?: unknown }).todo
  if (!candidate || typeof candidate !== 'object') return undefined
  if (!('todo_id' in candidate) || !('version' in candidate)) return undefined
  return candidate as LocalTodo
}

export function projectTodoError(error: unknown): TodoUiError {
  if (error instanceof ApiError) {
    if (error.status === 0 || error.code === 'TODO_COMMIT_UNCERTAIN') {
      return {
        code: 'TODO_UNKNOWN',
        message: '待办提交结果未确认：请先查询原回执，不要重复提交',
        unknown: true,
      }
    }
    if (error.code === 'TODO_VERSION_CONFLICT') {
      return {
        code: 'TODO_VERSION_CONFLICT',
        message: '待办已在其他窗口更新：当前输入已保留，已读取更新版本',
        unknown: false,
        currentTodo: errorCurrentTodo(error),
      }
    }
    if (error.code === 'TODO_REQUEST_CONFLICT') {
      return {
        code: 'TODO_REQUEST_CONFLICT',
        message: '该请求已用于不同待办内容：当前输入已保留，请重新发起',
        unknown: false,
      }
    }
    if (error.code === 'TODO_NOT_FOUND') {
      return {
        code: 'TODO_NOT_FOUND',
        message: '该待办不存在或已被删除：当前输入已保留',
        unknown: false,
      }
    }
    if (error.code === 'TODO_OPERATION_NOT_FOUND') {
      return {
        code: 'TODO_OPERATION_NOT_FOUND',
        message: '未找到原操作回执：可明确重试原请求',
        unknown: false,
      }
    }
    if (error.code === 'TODO_STORAGE_NOT_READY') {
      return {
        code: 'TODO_STORAGE_NOT_READY',
        message: '待办存储尚未就绪；数据库迁移完成后可用',
        unknown: false,
      }
    }
    return {
      code: error.code ?? 'TODO_REQUEST_FAILED',
      message: error.message || '待办请求失败，请稍后重试',
      unknown: false,
    }
  }
  return {
    code: 'TODO_REQUEST_FAILED',
    message: '待办请求失败，请稍后重试',
    unknown: false,
  }
}

const MAX_TITLE = 200

function cleanTitle(value: string): string | null {
  const title = value.trim()
  if (!title || title.length > MAX_TITLE) return null
  return title
}

function cleanDueDate(value: string): string | null | undefined {
  if (!value) return null
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(year, month - 1, day)
  if (
    Number.isNaN(parsed.getTime())
    || parsed.getFullYear() !== year
    || parsed.getMonth() !== month - 1
    || parsed.getDate() !== day
  ) {
    return undefined
  }
  return value
}

function todoOrder(left: LocalTodo, right: LocalTodo): number {
  if (left.completed !== right.completed) return left.completed ? 1 : -1
  if (left.due_date === null && right.due_date !== null) return 1
  if (left.due_date !== null && right.due_date === null) return -1
  if (left.due_date && right.due_date && left.due_date !== right.due_date) {
    return left.due_date < right.due_date ? -1 : 1
  }
  if (left.created_at !== right.created_at) {
    return left.created_at < right.created_at ? -1 : 1
  }
  return left.todo_id < right.todo_id ? -1 : left.todo_id > right.todo_id ? 1 : 0
}

export function createTodoStore(api: TodoApi = createTodoApi()) {
  const state = reactive({
    profileId: '',
    items: [] as LocalTodo[],
    loading: false,
    saving: false,
    checking: false,
    error: '',
    notice: '',
    conflict: false,
    draftTitle: '',
    draftDueDate: '',
    editingId: null as string | null,
    editingVersion: 0,
    pending: null as TodoWritePending | null,
    showArchived: false,
    selectedIds: [] as string[],
    batching: false,
    listReady: false,
  })
  let loadSeq = 0
  let mutationSeq = 0
  let draftSession = 0

  const busy = computed(
    () => state.saving || state.batching || state.checking || state.pending !== null,
  )
  const editing = computed(() => state.editingId !== null)

  function setProfile(profileId: string): void {
    if (!profileId || profileId === state.profileId) return
    loadSeq += 1
    state.profileId = profileId
    state.items = []
    state.loading = false
    state.saving = false
    state.checking = false
    state.error = ''
    state.notice = ''
    state.conflict = false
    state.draftTitle = ''
    state.draftDueDate = ''
    state.editingId = null
    state.editingVersion = 0
    state.pending = null
    state.showArchived = false
    state.selectedIds = []
    state.batching = false
    state.listReady = false
    mutationSeq += 1
    draftSession += 1
  }

  function inCurrentView(todo: LocalTodo): boolean {
    return Boolean(todo.archived_at) === state.showArchived
  }

  function applyTodo(todo: LocalTodo): boolean {
    const index = state.items.findIndex((item) => item.todo_id === todo.todo_id)
    if (!inCurrentView(todo)) {
      if (index < 0) return false
      if (state.items[index].version > todo.version) return false
      state.items.splice(index, 1)
      mutationSeq += 1
      return true
    }
    if (index >= 0) {
      if (state.items[index].version > todo.version) return false
      state.items[index] = todo
    } else {
      state.items.push(todo)
    }
    state.items.sort(todoOrder)
    mutationSeq += 1
    return true
  }

  function removeTodo(todoId: string, version?: number): boolean {
    const current = state.items.find((item) => item.todo_id === todoId)
    if (current && version !== undefined && current.version > version) return false
    state.items = state.items.filter((item) => item.todo_id !== todoId)
    mutationSeq += 1
    return true
  }

  function applyBatchResult(result: TodoOperationResult): boolean {
    const items = result.items ?? []
    let changed = false
    for (const item of items) {
      if (result.action === 'delete') {
        changed = removeTodo(item.todo_id, item.version) || changed
      } else {
        changed = applyTodo(item) || changed
      }
    }
    return changed
  }

  function applyResult(result: TodoOperationResult): boolean {
    if (result.items) return applyBatchResult(result)
    if (result.deleted && result.todo) {
      return removeTodo(result.todo.todo_id, result.todo.version)
    }
    if (result.todo) return applyTodo(result.todo)
    return false
  }

  function finishDraft(): void {
    state.draftTitle = ''
    state.draftDueDate = ''
    state.editingId = null
    state.editingVersion = 0
    state.conflict = false
    draftSession += 1
  }

  function finishOwnedDraft(pending: TodoWritePending): void {
    if (pending.ownsDraft && pending.draftSession === draftSession) {
      finishDraft()
    }
  }

  function applyConflict(projected: TodoUiError): void {
    state.conflict = true
    state.error = projected.message
    if (projected.currentTodo) {
      applyTodo(projected.currentTodo)
      if (state.editingId === projected.currentTodo.todo_id) {
        state.editingVersion = projected.currentTodo.version
      }
    }
  }

  async function load(profileId?: string): Promise<void> {
    if (profileId) setProfile(profileId)
    if (!state.profileId) return
    const seq = ++loadSeq
    const mutationAtStart = mutationSeq
    const profileAtStart = state.profileId
    state.loading = true
    state.error = ''
    try {
      const result = await api.list(state.showArchived)
      if (seq !== loadSeq || state.profileId !== profileAtStart) return
      if (mutationSeq !== mutationAtStart) {
        state.listReady = true
        return
      }
      state.items = [...result.items].sort(todoOrder)
      const present = new Set(state.items.map((item) => item.todo_id))
      state.selectedIds = state.selectedIds.filter((id) => present.has(id))
      state.listReady = true
      state.conflict = false
    } catch (error) {
      if (seq !== loadSeq) return
      state.error = projectTodoError(error).message
      state.listReady = false
    } finally {
      if (seq === loadSeq) state.loading = false
    }
  }

  async function setArchivedView(archived: boolean): Promise<void> {
    if (
      state.showArchived === archived
      || state.pending
      || state.batching
      || state.saving
      || state.loading
    ) return
    state.showArchived = archived
    state.items = []
    state.selectedIds = []
    state.listReady = false
    state.error = ''
    state.notice = ''
    await load()
  }

  function toggleSelected(todoId: string, selected: boolean): void {
    if (state.pending || state.batching || state.saving || !state.listReady) return
    const ids = new Set(state.selectedIds)
    if (selected) ids.add(todoId)
    else ids.delete(todoId)
    state.selectedIds = [...ids]
  }

  function clearSelection(): void {
    state.selectedIds = []
  }

  function startEdit(item: LocalTodo): void {
    if (state.pending || state.saving || state.batching || !state.listReady) return
    draftSession += 1
    state.editingId = item.todo_id
    state.editingVersion = item.version
    state.draftTitle = item.title
    state.draftDueDate = item.due_date ?? ''
    state.error = ''
    state.notice = ''
    state.conflict = false
  }

  function cancelEdit(): void {
    if (state.saving || state.batching) return
    finishDraft()
    state.error = ''
  }

  async function save(): Promise<void> {
    if (
      state.pending
      || state.saving
      || state.batching
      || !state.profileId
      || !state.listReady
    ) return
    const title = cleanTitle(state.draftTitle)
    if (!title) {
      state.error = '待办标题不能为空，且不超过 200 个字符'
      return
    }
    const dueDate = cleanDueDate(state.draftDueDate)
    if (dueDate === undefined) {
      state.error = '截止日必须是有效日期'
      return
    }
    const profileId = state.profileId
    const draftSessionAtStart = draftSession
    const requestId = crypto.randomUUID()
    const editingId = state.editingId
    const attempt: TodoWritePending = editingId
      ? {
          requestId,
          action: 'update',
          todoId: editingId,
          fields: {
            expected_version: state.editingVersion,
            title,
            due_date: dueDate,
          },
          ownsDraft: true,
          draftSession: draftSessionAtStart,
        }
      : {
          requestId,
          action: 'create',
          todoId: null,
          fields: { title, due_date: dueDate },
          ownsDraft: true,
          draftSession: draftSessionAtStart,
        }
    state.error = ''
    state.notice = ''
    state.saving = true
    try {
      if (attempt.action === 'create') {
        const todo = await api.create({ request_id: requestId, ...attempt.fields })
        if (state.profileId !== profileId) return
        applyTodo(todo)
        state.notice = '待办已新建'
      } else {
        const todo = await api.update(attempt.todoId!, {
          request_id: requestId,
          ...attempt.fields,
        })
        if (state.profileId !== profileId) return
        applyTodo(todo)
        state.notice = '待办已保存'
      }
      finishDraft()
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      if (projected.unknown) {
        state.pending = attempt
        state.notice = projected.message
      } else if (projected.code === 'TODO_VERSION_CONFLICT') {
        applyConflict(projected)
      } else {
        state.error = projected.message
      }
    } finally {
      if (state.profileId === profileId) state.saving = false
    }
  }

  async function toggle(item: LocalTodo): Promise<void> {
    if (state.pending || state.saving || state.batching || !state.listReady) return
    const profileId = state.profileId
    const requestId = crypto.randomUUID()
    const attempt: TodoWritePending = {
      requestId,
      action: 'update',
      todoId: item.todo_id,
      fields: { expected_version: item.version, completed: !item.completed },
      ownsDraft: false,
      draftSession,
    }
    state.error = ''
    state.notice = ''
    state.saving = true
    try {
      const todo = await api.update(item.todo_id, {
        request_id: requestId,
        ...attempt.fields,
      })
      if (state.profileId !== profileId) return
      applyTodo(todo)
      state.conflict = false
      state.notice = todo.completed ? '待办已完成' : '待办已恢复'
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      if (projected.unknown) {
        state.pending = attempt
        state.notice = projected.message
      } else if (projected.code === 'TODO_VERSION_CONFLICT') {
        applyConflict(projected)
      } else {
        state.error = projected.message
      }
    } finally {
      if (state.profileId === profileId) state.saving = false
    }
  }

  async function remove(item: LocalTodo): Promise<void> {
    if (state.pending || state.saving || state.batching || !state.listReady) return
    const profileId = state.profileId
    const requestId = crypto.randomUUID()
    const attempt: TodoWritePending = {
      requestId,
      action: 'delete',
      todoId: item.todo_id,
      fields: { expected_version: item.version },
      ownsDraft: state.editingId === item.todo_id,
      draftSession,
    }
    state.error = ''
    state.notice = ''
    state.saving = true
    try {
      const result = await api.remove(item.todo_id, {
        request_id: requestId,
        ...attempt.fields,
      })
      if (state.profileId !== profileId) return
      applyResult(result)
      state.conflict = false
      state.notice = '待办已删除'
      finishOwnedDraft(attempt)
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      if (projected.unknown) {
        state.pending = attempt
        state.notice = projected.message
      } else if (projected.code === 'TODO_VERSION_CONFLICT') {
        applyConflict(projected)
      } else {
        state.error = projected.message
      }
    } finally {
      if (state.profileId === profileId) state.saving = false
    }
  }

  async function runBatch(
    action: 'archive' | 'delete',
    selected: LocalTodo[],
  ): Promise<void> {
    if (
      state.pending
      || state.saving
      || state.batching
      || !state.profileId
      || !state.listReady
    ) return
    const unique = [...new Map(selected.map((item) => [item.todo_id, item])).values()]
    if (!unique.length) return
    if (action === 'archive' && unique.some((item) => !item.completed)) {
      state.error = '只能归档已完成的待办'
      return
    }
    if (action === 'archive' && unique.some((item) => item.archived_at)) {
      state.error = '所选待办已归档'
      return
    }
    const profileId = state.profileId
    const requestId = crypto.randomUUID()
    const items = unique.map((item) => ({
      todo_id: item.todo_id,
      expected_version: item.version,
    }))
    const attempt: TodoWritePending = {
      requestId,
      action: action === 'archive' ? 'batch_archive' : 'batch_delete',
      todoId: null,
      fields: { action, items },
      ownsDraft: false,
      draftSession,
    }
    state.error = ''
    state.notice = ''
    state.batching = true
    try {
      const result = await api.batch({
        request_id: requestId,
        action,
        items,
      })
      if (state.profileId !== profileId) return
      applyResult(result)
      state.conflict = false
      state.selectedIds = []
      const count = result.items?.length ?? items.length
      state.notice = action === 'archive'
        ? `已归档 ${count} 项待办`
        : `已删除 ${count} 项待办`
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      if (projected.unknown) {
        state.pending = attempt
        state.notice = projected.message
      } else if (projected.code === 'TODO_VERSION_CONFLICT') {
        applyConflict(projected)
      } else {
        state.error = projected.message
      }
    } finally {
      if (state.profileId === profileId) state.batching = false
    }
  }

  function archiveBatch(items: LocalTodo[]): Promise<void> {
    return runBatch('archive', items)
  }

  function deleteBatch(items: LocalTodo[]): Promise<void> {
    return runBatch('delete', items)
  }

  async function queryPending(): Promise<void> {
    const pending = state.pending
    if (!pending || state.saving || state.batching || state.checking) return
    const profileId = state.profileId
    state.checking = true
    state.error = ''
    try {
      const result = await api.operation(pending.requestId)
      if (state.profileId !== profileId) return
      applyResult(result)
      state.pending = null
      state.selectedIds = []
      state.notice = '已恢复原操作结果'
      finishOwnedDraft(pending)
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      state.notice = projected.message
    } finally {
      if (state.profileId === profileId) state.checking = false
    }
  }

  async function retryPending(): Promise<void> {
    const pending = state.pending
    if (!pending || state.saving || state.checking) return
    const profileId = state.profileId
    state.saving = true
    state.error = ''
    try {
      let result: TodoOperationResult
      if (
        pending.action === 'batch_archive'
        || pending.action === 'batch_delete'
      ) {
        result = await api.batch({
          request_id: pending.requestId,
          ...pending.fields,
        })
      } else if (pending.action === 'create') {
        result = {
          todo: await api.create({
            request_id: pending.requestId,
            ...pending.fields,
          }),
        }
      } else if (pending.action === 'delete') {
        result = await api.remove(pending.todoId!, {
          request_id: pending.requestId,
          ...pending.fields,
        })
      } else {
        result = {
          todo: await api.update(pending.todoId!, {
            request_id: pending.requestId,
            ...pending.fields,
          }),
        }
      }
      if (state.profileId !== profileId) return
      applyResult(result)
      state.pending = null
      state.selectedIds = []
      state.notice = '原请求已确认'
      finishOwnedDraft(pending)
    } catch (error) {
      if (state.profileId !== profileId) return
      const projected = projectTodoError(error)
      if (projected.code === 'TODO_VERSION_CONFLICT') {
        // A same-key replay returns its receipt before any version check.  A
        // conflict therefore proves the original request did not commit and
        // can never commit with its frozen expected version; keep the draft,
        // show the updated version, and let the teacher save explicitly.
        state.pending = null
        applyConflict(projected)
        state.notice = '原请求未提交：已读取更新版本，当前输入已保留，请确认后再次保存'
      } else if (projected.code === 'TODO_REQUEST_CONFLICT') {
        state.pending = null
        state.error = projected.message
        state.notice = '原请求未提交：请核对当前输入后重新发起'
      } else {
        // Any ordinary failure after an unknown write keeps the original
        // request key and still-unconfirmed state.
        state.error = projected.message
        state.notice = '原请求仍未确认：请查回执或明确重试原请求'
      }
    } finally {
      if (state.profileId === profileId) state.saving = false
    }
  }

  return {
    state,
    busy,
    editing,
    setProfile,
    setArchivedView,
    toggleSelected,
    clearSelection,
    load,
    startEdit,
    cancelEdit,
    save,
    toggle,
    remove,
    archiveBatch,
    deleteBatch,
    queryPending,
    retryPending,
  }
}

export type TodoStore = ReturnType<typeof createTodoStore>

export const todoStore = createTodoStore()
