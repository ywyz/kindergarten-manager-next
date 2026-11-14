/**
 * #13 pure personal-todo store/client tests.  No database, HTTP server or
 * browser: a synthetic API double persists the same todos and receipt results
 * across store instances, including one reopen and unknown/failure cases.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function makeTodo(id, title, due = null, version = 1) {
  return {
    todo_id: id,
    title,
    due_date: due,
    completed: false,
    archived_at: null,
    version,
    created_at: `2026-11-0${version}T10:00:00`,
    updated_at: `2026-11-0${version}T10:00:00`,
  }
}

class FakeTodoApi {
  constructor() {
    this.items = []
    this.operations = new Map()
    this.seq = 0
    this.unknownNext = false
    this.failNext = false
    this.commitUnknownNext = false
    this.unknownPreCommitNext = false
    this.failRetryNext = false
    this.listGate = null
    this.listFailNext = false
    this.gate = null
    this.batchCalls = 0
  }

  _copy(value) {
    return JSON.parse(JSON.stringify(value))
  }

  _receipt(requestId, result) {
    this.operations.set(requestId, this._copy(result))
    return result
  }

  _replay(requestId) {
    return this.operations.has(requestId)
      ? this._copy(this.operations.get(requestId))
      : null
  }

  async list(archived = false) {
    if (this.listFailNext) {
      this.listFailNext = false
      throw new ApiError(500, '合成列表失败', 'TODO_INTERNAL')
    }
    if (this.listGate) await this.listGate.promise
    return {
      items: this._copy(
        this.items.filter((item) => Boolean(item.archived_at) === archived),
      ),
    }
  }

  async create(body) {
    if (this.failRetryNext) {
      this.failRetryNext = false
      throw new ApiError(500, '合成重试失败', 'TODO_INTERNAL')
    }
    const replay = this._replay(body.request_id)
    if (replay) return replay.todo
    if (this.failNext) {
      this.failNext = false
      throw new ApiError(500, '合成保存失败', 'TODO_INTERNAL')
    }
    if (this.gate) await this.gate.promise
    this.seq += 1
    const todo = makeTodo(
      `t${this.seq}`,
      body.title,
      body.due_date ?? null,
      1,
    )
    this.items.push(todo)
    this._receipt(body.request_id, { todo: this._copy(todo) })
    if (this.commitUnknownNext) {
      this.commitUnknownNext = false
      throw new ApiError(503, '提交结果不确定', 'TODO_COMMIT_UNCERTAIN')
    }
    if (this.unknownNext) {
      this.unknownNext = false
      throw new ApiError(0, '合成网络中断')
    }
    return this._copy(todo)
  }

  async update(todoId, body) {
    if (this.failRetryNext) {
      this.failRetryNext = false
      throw new ApiError(500, '合成重试失败', 'TODO_INTERNAL')
    }
    const replay = this._replay(body.request_id)
    if (replay) return replay.todo
    if (this.unknownPreCommitNext) {
      this.unknownPreCommitNext = false
      throw new ApiError(0, '合成网络中断（未提交）')
    }
    const item = this.items.find((row) => row.todo_id === todoId)
    if (!item) throw new ApiError(404, '待办不存在', 'TODO_NOT_FOUND')
    if (item.version !== body.expected_version) {
      throw new ApiError(409, '版本冲突', 'TODO_VERSION_CONFLICT', {
        todo: this._copy(item),
      })
    }
    if (this.failNext) {
      this.failNext = false
      throw new ApiError(500, '合成保存失败', 'TODO_INTERNAL')
    }
    if ('title' in body) item.title = body.title
    if ('due_date' in body) item.due_date = body.due_date
    if ('completed' in body) item.completed = body.completed
    item.version += 1
    item.updated_at = `2026-11-0${item.version}T10:00:00`
    this._receipt(body.request_id, { todo: this._copy(item) })
    if (this.commitUnknownNext) {
      this.commitUnknownNext = false
      throw new ApiError(503, '提交结果不确定', 'TODO_COMMIT_UNCERTAIN')
    }
    if (this.unknownNext) {
      this.unknownNext = false
      throw new ApiError(0, '合成网络中断')
    }
    return this._copy(item)
  }

  async unarchive(todoId, body) {
    if (this.failRetryNext) {
      this.failRetryNext = false
      throw new ApiError(500, '合成重试失败', 'TODO_INTERNAL')
    }
    const replay = this._replay(body.request_id)
    if (replay) return replay.todo
    if (this.unknownPreCommitNext) {
      this.unknownPreCommitNext = false
      throw new ApiError(0, '合成网络中断（未提交）')
    }
    const item = this.items.find((row) => row.todo_id === todoId)
    if (!item) throw new ApiError(404, '待办不存在', 'TODO_NOT_FOUND')
    if (item.version !== body.expected_version) {
      throw new ApiError(409, '版本冲突', 'TODO_VERSION_CONFLICT', {
        todo: this._copy(item),
      })
    }
    if (!item.archived_at) {
      throw new ApiError(422, '待办未归档', 'TODO_INVALID')
    }
    item.archived_at = null
    item.version += 1
    item.updated_at = `2026-11-0${item.version}T10:00:00`
    this._receipt(body.request_id, { todo: this._copy(item) })
    if (this.commitUnknownNext) {
      this.commitUnknownNext = false
      throw new ApiError(503, '提交结果不确定', 'TODO_COMMIT_UNCERTAIN')
    }
    if (this.unknownNext) {
      this.unknownNext = false
      throw new ApiError(0, '合成网络中断')
    }
    return this._copy(item)
  }

  async remove(todoId, body) {
    if (this.failRetryNext) {
      this.failRetryNext = false
      throw new ApiError(500, '合成重试失败', 'TODO_INTERNAL')
    }
    const replay = this._replay(body.request_id)
    if (replay) return replay
    const index = this.items.findIndex((row) => row.todo_id === todoId)
    if (index < 0) throw new ApiError(404, '待办不存在', 'TODO_NOT_FOUND')
    const item = this.items[index]
    if (item.version !== body.expected_version) {
      throw new ApiError(409, '版本冲突', 'TODO_VERSION_CONFLICT', {
        todo: this._copy(item),
      })
    }
    this.items.splice(index, 1)
    const result = { deleted: true, todo: this._copy(item) }
    this._receipt(body.request_id, result)
    if (this.commitUnknownNext) {
      this.commitUnknownNext = false
      throw new ApiError(503, '提交结果不确定', 'TODO_COMMIT_UNCERTAIN')
    }
    if (this.unknownNext) {
      this.unknownNext = false
      throw new ApiError(0, '合成网络中断')
    }
    return result
  }

  async batch(body) {
    this.batchCalls += 1
    if (this.failRetryNext) {
      this.failRetryNext = false
      throw new ApiError(500, '合成重试失败', 'TODO_INTERNAL')
    }
    const replay = this._replay(body.request_id)
    if (replay) return replay
    if (body.action !== 'archive' && body.action !== 'delete') {
      throw new ApiError(422, '合成批量动作非法', 'TODO_INVALID')
    }
    if (!Array.isArray(body.items) || !body.items.length) {
      throw new ApiError(422, '合成批量项目为空', 'TODO_INVALID')
    }
    const ids = new Set()
    const rows = []
    for (const item of body.items) {
      if (ids.has(item.todo_id)) {
        throw new ApiError(422, '合成批量 ID 重复', 'TODO_INVALID')
      }
      ids.add(item.todo_id)
      const row = this.items.find((candidate) => candidate.todo_id === item.todo_id)
      if (!row) throw new ApiError(404, '待办不存在', 'TODO_NOT_FOUND')
      if (row.version !== item.expected_version) {
        throw new ApiError(409, '版本冲突', 'TODO_VERSION_CONFLICT', {
          todo: this._copy(row),
        })
      }
      if (body.action === 'archive' && !row.completed) {
        throw new ApiError(422, '只能归档已完成的待办', 'TODO_INVALID')
      }
      rows.push(row)
    }
    if (this.failNext) {
      this.failNext = false
      throw new ApiError(500, '合成批量失败', 'TODO_INTERNAL')
    }
    if (this.gate) await this.gate.promise
    const resultItems = []
    for (const row of rows) {
      if (body.action === 'archive') {
        row.archived_at = '2026-11-11T12:00:00'
        row.version += 1
        row.updated_at = '2026-11-11T12:00:00'
        resultItems.push(this._copy(row))
      } else {
        resultItems.push(this._copy(row))
      }
    }
    if (body.action === 'delete') {
      this.items = this.items.filter((row) => !ids.has(row.todo_id))
    }
    const result = {
      action: body.action,
      items: resultItems,
      deleted: body.action === 'delete',
    }
    this._receipt(body.request_id, result)
    if (this.commitUnknownNext) {
      this.commitUnknownNext = false
      throw new ApiError(503, '提交结果不确定', 'TODO_COMMIT_UNCERTAIN')
    }
    if (this.unknownNext) {
      this.unknownNext = false
      throw new ApiError(0, '合成网络中断')
    }
    return this._copy(result)
  }

  async operation(requestId) {
    const result = this._replay(requestId)
    if (!result) {
      throw new ApiError(404, '未找到回执', 'TODO_OPERATION_NOT_FOUND')
    }
    return result
  }
}

function loadTodoModule(api) {
  const file = path.join(d1Dir, 'todos.ts')
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: file,
  }).outputText
  const client = {
    ApiError,
    pathSegment: (value) => encodeURIComponent(String(value)),
    apiGet: async (url) => {
      if (url === '/api/local/todos') return api.list(false)
      if (url === '/api/local/todos?archived=true') return api.list(true)
      const match = String(url).match(/\/api\/local\/todos\/operations\/([^/]+)$/)
      if (match) return api.operation(decodeURIComponent(match[1]))
      throw new ApiError(404, `unexpected GET ${url}`)
    },
    apiPost: async (url, body) => {
      if (url === '/api/local/todos') return api.create(body)
      const unarchive = String(url).match(/\/api\/local\/todos\/([^/]+)\/unarchive$/)
      if (unarchive) return api.unarchive(decodeURIComponent(unarchive[1]), body)
      if (url === '/api/local/todos/batch') return api.batch(body)
      throw new ApiError(404, `unexpected POST ${url}`)
    },
    apiPatch: async (url, body) => {
      const match = String(url).match(/\/api\/local\/todos\/([^/]+)$/)
      if (match) return api.update(decodeURIComponent(match[1]), body)
      throw new ApiError(404, `unexpected PATCH ${url}`)
    },
    apiDelete: async (url, body) => {
      const match = String(url).match(/\/api\/local\/todos\/([^/]+)$/)
      if (match) return api.remove(decodeURIComponent(match[1]), body)
      throw new ApiError(404, `unexpected DELETE ${url}`)
    },
  }
  let uuid = 0
  const module = { exports: {} }
  vm.runInNewContext(
    js,
    {
      module,
      exports: module.exports,
      require: (spec) => {
        if (spec === 'vue') return vue
        if (spec === './client') return client
        throw new Error(`unexpected import ${spec}`)
      },
      console,
      Date,
      JSON,
      Object,
      Array,
      String,
      Number,
      Boolean,
      Promise,
      Map,
      Set,
      crypto: { randomUUID: () => `req-${++uuid}` },
    },
    { filename: file },
  )
  return module.exports
}

const source = fs.readFileSync(path.join(d1Dir, 'views', 'WorkbenchView.vue'), 'utf8')
assert.match(source, /<WorkbenchTodoPanel/)
assert.match(source, /:profile-id="props\.context\.profile\?\.id \?\? ''"/)
assert.match(source, /:disabled="frozen"/)
assert.match(source, /@busy="onTodoBusy"/)
assert.match(source, /emit\('busy', value\)/)
const app = fs.readFileSync(path.join(d1Dir, 'App.vue'), 'utf8')
assert.match(app, /todoStore/)
assert.match(app, /workbenchBusy/)
assert.match(app, /workbenchBusy\.value \|\|/)
assert.match(app, /个人待办写入或未决结果尚未核对/)
const panel = fs.readFileSync(path.join(d1Dir, 'views', 'WorkbenchTodoPanel.vue'), 'utf8')
for (const marker of [
  'data-d1="workbench-todos"', 'data-d1="todo-title"', 'data-d1="todo-due"',
  'data-d1="todo-save"', 'data-d1="todo-pending"', 'data-d1="todo-query"',
  'data-d1="todo-retry"', 'todo-row-',
  'data-d1="todo-view-active"', 'data-d1="todo-view-archived"',
  'data-d1="todo-batch-archive"', 'data-d1="todo-batch-delete"',
  'data-d1="todo-selected-count"', 'todo-select-',
  'todo-unarchive-', 'todo-complete-toggle', 'todo-select-box',
  '确认归档已完成的', '确认删除所选的',
]) assert.ok(panel.includes(marker), marker)
assert.match(panel, /:aria-pressed="item\.completed"/)
assert.match(panel, /border-radius:\s*50%/)
ok('workbench normal entry and minimal todo controls are present')

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  assert.equal(store.state.items.length, 0)
  assert.equal(store.busy.value, false)

  store.state.draftTitle = '买彩纸'
  store.state.draftDueDate = '2026-11-30'
  await store.save()
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].title, '买彩纸')
  assert.equal(store.state.items[0].due_date, '2026-11-30')
  assert.equal(store.state.draftTitle, '')
  assert.equal(store.state.pending, null)

  store.startEdit(store.state.items[0])
  store.state.draftTitle = '买彩纸和胶棒'
  await store.save()
  assert.equal(store.state.items[0].title, '买彩纸和胶棒')
  assert.equal(store.state.items[0].version, 2)

  await store.toggle(store.state.items[0])
  assert.equal(store.state.items[0].completed, true)
  assert.equal(store.state.items[0].version, 3)
  assert.equal(store.state.notice, '待办已完成')

  const reopened = mod.createTodoStore(api)
  reopened.setProfile('p1')
  await reopened.load()
  assert.equal(reopened.state.items.length, 1)
  assert.equal(reopened.state.items[0].title, '买彩纸和胶棒')
  assert.equal(reopened.state.items[0].completed, true)

  await reopened.remove(reopened.state.items[0])
  assert.equal(reopened.state.items.length, 0)
  assert.equal(reopened.state.notice, '待办已删除')

  const before = api.seq
  reopened.state.draftTitle = '双击只建一条'
  const firstClick = reopened.save()
  const secondClick = reopened.save()
  await Promise.all([firstClick, secondClick])
  assert.equal(api.seq, before + 1)
  assert.equal(reopened.state.items.length, 1)
  ok('create/edit/complete/delete, reopen and duplicate rapid save work without a database')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.unknownNext = true
  store.state.draftTitle = '未决新建'
  await store.save()
  assert.equal(store.state.pending?.action, 'create')
  assert.equal(store.state.draftTitle, '未决新建')
  assert.equal(store.state.items.length, 0)
  assert.equal(store.busy.value, true)

  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].title, '未决新建')
  assert.equal(store.state.draftTitle, '')
  assert.equal(store.busy.value, false)
  ok('an unknown create keeps the exact draft and request, then resolves through the old receipt')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.failNext = true
  store.state.draftTitle = '失败保留'
  await store.save()
  assert.equal(store.state.items.length, 0)
  assert.equal(store.state.draftTitle, '失败保留')
  assert.match(store.state.error, /失败/)
  assert.equal(store.state.pending, null)

  store.state.draftTitle = '版本冲突'
  await store.save()
  const item = store.state.items[0]
  store.startEdit(item)
  store.state.draftTitle = '冲突输入'
  api.items[0].version += 1
  await store.save()
  assert.equal(store.state.draftTitle, '冲突输入')
  assert.match(store.state.error, /其他窗口/)
  assert.equal(store.state.items[0].title, '版本冲突')
  assert.equal(store.state.items[0].version, 2)
  assert.equal(store.state.editingVersion, 2)
  assert.equal(store.state.conflict, true)
  await store.save()
  assert.equal(store.state.items[0].title, '冲突输入')
  assert.equal(store.state.conflict, false)
  ok('save failure and version conflict preserve the draft, show the updated version and allow an explicit resubmit')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  const gate = deferred()
  api.gate = gate
  store.state.draftTitle = '旧档案待办'
  const saving = store.save()
  store.setProfile('p2')
  gate.resolve()
  await saving
  assert.equal(store.state.profileId, 'p2')
  assert.equal(store.state.items.length, 0)
  assert.equal(store.state.pending, null)
  ok('a late result from the old profile cannot repopulate the new profile store')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  const gate = deferred()
  api.listGate = gate
  const oldLoad = store.load()
  store.state.draftTitle = '新建成功'
  await store.save()
  gate.resolve({ items: [] })
  await oldLoad
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].title, '新建成功')
  ok('a list GET started before a confirmed create cannot overwrite the new item')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [makeTodo('tA', '甲待办'), makeTodo('tB', '乙待办')]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  const a = store.state.items.find((item) => item.todo_id === 'tA')
  const b = store.state.items.find((item) => item.todo_id === 'tB')
  store.startEdit(a)
  store.state.draftTitle = '甲正在编辑的草稿'
  api.unknownNext = true
  await store.toggle(b)
  assert.equal(store.state.pending?.todoId, 'tB')
  assert.equal(store.state.editingId, 'tA')
  assert.equal(store.state.draftTitle, '甲正在编辑的草稿')
  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.editingId, 'tA')
  assert.equal(store.state.draftTitle, '甲正在编辑的草稿')
  assert.equal(store.state.items.find((item) => item.todo_id === 'tB').completed, true)
  ok('recovering another item cannot clear the draft of the item currently being edited')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.commitUnknownNext = true
  store.state.draftTitle = '提交未决'
  await store.save()
  assert.equal(store.state.pending?.action, 'create')
  assert.equal(store.state.draftTitle, '提交未决')
  assert.equal(store.state.items.length, 0)

  api.failRetryNext = true
  await store.retryPending()
  assert.ok(store.state.pending)
  assert.match(store.state.notice, /仍未确认/)
  assert.equal(store.state.items.length, 0)

  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].title, '提交未决')
  ok('commit-uncertain is pending, an ordinary retry failure keeps its ticket, and the receipt resolves it')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [makeTodo('t1', '原待办')]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  store.startEdit(store.state.items[0])
  store.state.draftTitle = '未提交修改'
  api.unknownPreCommitNext = true
  await store.save()
  assert.equal(store.state.pending?.action, 'update')
  assert.equal(store.state.items[0].title, '原待办')
  assert.equal(store.state.draftTitle, '未提交修改')

  api.items[0].title = '其他窗口新版本'
  api.items[0].version = 2
  await store.retryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.conflict, true)
  assert.equal(store.state.editingVersion, 2)
  assert.equal(store.state.draftTitle, '未提交修改')
  assert.match(store.state.notice, /原请求未提交/)

  await store.save()
  assert.equal(store.state.items[0].title, '未提交修改')
  assert.equal(store.state.items[0].version, 3)
  assert.equal(store.state.pending, null)
  ok('a same-key retry conflict proves non-commit and reopens an explicit save with the updated version')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  const created = await api.create({ request_id: 'seed', title: '旧版本' })
  await store.load()
  store.startEdit(store.state.items[0])
  store.state.draftTitle = '第一版修改'
  api.unknownNext = true
  await store.save()
  assert.equal(store.state.pending?.action, 'update')
  await api.update(created.todo_id, {
    request_id: 'newer-write',
    expected_version: 2,
    title: '其他窗口新版本',
  })
  await store.load()
  assert.equal(store.state.items[0].title, '其他窗口新版本')
  assert.equal(store.state.items[0].version, 3)
  await store.queryPending()
  assert.equal(store.state.items[0].title, '其他窗口新版本')
  assert.equal(store.state.items[0].version, 3)
  assert.equal(store.state.pending, null)
  ok('an old confirmed receipt cannot overwrite a newer item version')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    { ...makeTodo('a1', '完成甲'), completed: true },
    { ...makeTodo('a2', '完成乙'), completed: true },
    { ...makeTodo('a3', '未完成'), completed: false },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  store.state.draftTitle = '切换视图也不丢的草稿'
  store.toggleSelected('a1', true)
  store.toggleSelected('a2', true)
  assert.equal(store.state.selectedIds.length, 2)
  await store.archiveBatch(store.state.items.filter((item) => item.completed))
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].todo_id, 'a3')
  assert.equal(store.state.selectedIds.length, 0)
  assert.equal(store.state.draftTitle, '切换视图也不丢的草稿')
  assert.match(store.state.notice, /已归档 2 项/)

  await store.setArchivedView(true)
  assert.equal(store.state.showArchived, true)
  assert.equal(store.state.items.length, 2)
  assert.ok(store.state.items.every((item) => item.archived_at))
  assert.equal(store.state.draftTitle, '切换视图也不丢的草稿')

  await store.deleteBatch(store.state.items)
  assert.equal(store.state.items.length, 0)
  await store.setArchivedView(false)
  assert.equal(store.state.showArchived, false)
  assert.equal(api.items.length, 1)
  assert.equal(api.items[0].todo_id, 'a3')
  ok('completed selection archives, archived view loads, batch delete confirms, and drafts survive view switches')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [{ ...makeTodo('b1', '完成'), completed: true }]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.commitUnknownNext = true
  await store.archiveBatch([store.state.items[0]])
  assert.equal(store.state.pending?.action, 'batch_archive')
  assert.equal(store.state.items.length, 1)
  assert.equal(store.busy.value, true)
  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 0)
  assert.equal(store.busy.value, false)
  ok('an unknown batch archive keeps its original request and resolves from the receipt')
}
{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    { ...makeTodo('c1', '完成一'), completed: true },
    { ...makeTodo('c2', '完成二'), completed: true },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  store.toggleSelected('c1', true)
  store.toggleSelected('c2', true)
  const gate = deferred()
  api.gate = gate
  const first = store.archiveBatch(store.state.items)
  const second = store.archiveBatch(store.state.items)
  assert.equal(store.state.batching, true)
  assert.equal(api.batchCalls, 1)
  gate.resolve()
  await Promise.all([first, second])
  assert.equal(store.state.batching, false)
  assert.equal(api.batchCalls, 1)
  ok('batch actions are single-flight and never send a duplicate while pending')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    { ...makeTodo('d1', '完成一'), completed: true },
    { ...makeTodo('d2', '完成二'), completed: true },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.items[1].version = 2
  await store.archiveBatch(store.state.items)
  assert.match(store.state.error, /其他窗口/)
  assert.equal(store.state.pending, null)
  assert.ok(api.items.every((item) => item.archived_at === null))
  assert.equal(store.state.items.length, 2)
  ok('a batch version conflict changes no rows and keeps the selected working list')
}
{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    { ...makeTodo('active', '活动待办'), completed: false },
    { ...makeTodo('old', '已归档'), completed: true, archived_at: '2026-11-01T10:00:00' },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  store.startEdit(store.state.items.find((item) => item.todo_id === 'active'))
  store.state.draftTitle = '活动草稿改标题'
  await store.setArchivedView(true)
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].todo_id, 'old')
  store.state.draftTitle = '归档视图里继续保存活动草稿'
  await store.save()
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].todo_id, 'old')
  assert.equal(api.items.find((item) => item.todo_id === 'active').title, '归档视图里继续保存活动草稿')
  store.state.draftTitle = '归档视图新建'
  await store.save()
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.showArchived, true)
  assert.equal(api.items.filter((item) => !item.archived_at).length, 2)
  await store.setArchivedView(false)
  assert.equal(store.state.items.length, 2)
  ok('active drafts and new rows never leak into the archived projection')
}
{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [{ ...makeTodo('live', '活动行') }]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  store.toggleSelected('live', true)
  api.listFailNext = true
  await store.setArchivedView(true)
  assert.equal(store.state.showArchived, true)
  assert.equal(store.state.items.length, 0)
  assert.equal(store.state.selectedIds.length, 0)
  assert.equal(store.state.listReady, false)
  store.toggleSelected('live', true)
  assert.equal(store.state.selectedIds.length, 0)
  await store.load()
  assert.equal(store.state.listReady, true)
  assert.equal(store.state.items.length, 0)
  ok('a failed view GET clears the old projection and keeps a retryable empty view')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [{ ...makeTodo('stale', '并发项'), completed: true }]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.load()
  api.commitUnknownNext = true
  await store.archiveBatch([store.state.items[0]])
  assert.equal(store.state.pending?.action, 'batch_archive')
  store.state.items[0].version = 3
  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].todo_id, 'stale')
  assert.equal(store.state.items[0].version, 3)
  assert.equal(store.state.items[0].archived_at, null)
  ok('a stale batch receipt cannot remove a newer visible row')
}
{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    {
      ...makeTodo('u1', '已归档待办'),
      completed: true,
      archived_at: '2026-11-01T10:00:00',
    },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.setArchivedView(true)
  assert.equal(store.state.items.length, 1)
  await store.unarchive(store.state.items[0])
  assert.equal(store.state.items.length, 0)
  assert.equal(store.state.notice, '待办已取消归档')
  assert.equal(api.items[0].completed, true)
  assert.equal(api.items[0].archived_at, null)
  assert.equal(api.items[0].version, 2)
  await store.setArchivedView(false)
  assert.equal(store.state.items.length, 1)
  assert.equal(store.state.items[0].todo_id, 'u1')
  assert.equal(store.state.items[0].completed, true)
  ok('unarchive returns the archived item to the active list with completion preserved')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    {
      ...makeTodo('u2', '未决取消归档'),
      completed: true,
      archived_at: '2026-11-01T10:00:00',
    },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.setArchivedView(true)
  api.commitUnknownNext = true
  await store.unarchive(store.state.items[0])
  assert.equal(store.state.pending?.action, 'unarchive')
  assert.equal(store.state.items.length, 1)
  assert.equal(store.busy.value, true)
  await store.queryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 0)
  assert.equal(store.busy.value, false)
  ok('an unknown unarchive resolves from the original receipt')
}

{
  const api = new FakeTodoApi()
  const mod = loadTodoModule(api)
  api.items = [
    {
      ...makeTodo('u3', '重试取消归档'),
      completed: true,
      archived_at: '2026-11-01T10:00:00',
    },
  ]
  const store = mod.createTodoStore(api)
  store.setProfile('p1')
  await store.setArchivedView(true)
  api.unknownPreCommitNext = true
  await store.unarchive(store.state.items[0])
  assert.equal(store.state.pending?.action, 'unarchive')
  await store.retryPending()
  assert.equal(store.state.pending, null)
  assert.equal(store.state.items.length, 0)
  assert.equal(api.items[0].archived_at, null)
  assert.equal(api.items[0].completed, true)
  ok('explicit retry replays the original unarchive request')
}

console.log(`\n${passed} todo checks passed`)
