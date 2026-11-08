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
    this.gate = null
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

  async list() {
    if (this.listGate) await this.listGate.promise
    return { items: this._copy(this.items) }
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
      if (url === '/api/local/todos') return api.list()
      const match = String(url).match(/\/api\/local\/todos\/operations\/([^/]+)$/)
      if (match) return api.operation(decodeURIComponent(match[1]))
      throw new ApiError(404, `unexpected GET ${url}`)
    },
    apiPost: async (url, body) => {
      if (url === '/api/local/todos') return api.create(body)
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
]) assert.ok(panel.includes(marker), marker)
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

console.log(`\n${passed} todo checks passed`)
