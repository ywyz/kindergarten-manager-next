/**
 * Optional Nextcloud Tasks (CalDAV) todo sync store + panel source checks.
 *
 * No database, HTTP server, browser or real Nextcloud service: the store is
 * driven by a synthetic API double, and the panels are checked by compiling
 * the real SFC sources.  The Nextcloud password only ever travels from the
 * connect form to the API call; it is never part of any status view.
 *
 * Run with:  node src/d1/d1.todo-sync.test.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import * as vue from 'vue'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

async function flush() {
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate
    }
  }
  return null
}

class ScriptCache {
  constructor() {
    this.cache = new Map()
    this.seq = 0
  }

  load(file) {
    if (this.cache.has(file)) return this.cache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: file,
    })
    const cache = this
    const module = { exports: {} }
    const context = vm.createContext({
      module,
      exports: module.exports,
      require: (spec) => {
        if (spec === 'vue') return vue
        if (spec.startsWith('.')) {
          const resolved = resolveTsFile(spec, file)
          if (resolved) return cache.load(resolved)
        }
        throw new Error(`unexpected require: ${spec}`)
      },
      console,
      crypto: { randomUUID: () => `rid-${(this.seq += 1)}` },
    })
    vm.runInContext(outputText, context)
    const value = module.exports
    this.cache.set(file, value)
    return value
  }
}

class FakeSyncApi {
  constructor() {
    this.statusValue = {
      setting: { configured: false, enabled: false, setting_version: 0 },
      credential: { configured: false },
    }
    this.listsValue = { lists: [], selected: null, enabled: false }
    this.calls = []
    this.failConnect = null
    this.failSelect = null
    this.syncResult = null
    this.connected = null
  }

  async status() {
    this.calls.push('status')
    return JSON.parse(JSON.stringify(this.statusValue))
  }

  async connect(input) {
    this.calls.push({ name: 'connect', input })
    if (this.failConnect) {
      throw this.failConnect
    }
    this.connected = input
    this.statusValue = {
      setting: {
        configured: true,
        enabled: false,
        server_url: input.url,
        username: input.username,
        setting_version: 1,
        list_href: null,
        list_name: null,
        last_sync_at: null,
        last_result: null,
      },
      credential: {
        configured: true,
        url: input.url,
        username: input.username,
        password_available: true,
      },
    }
    return {
      ok: true,
      enabled: false,
      server_url: input.url,
      username: input.username,
      setting_version: 1,
    }
  }

  async lists() {
    this.calls.push('lists')
    return JSON.parse(JSON.stringify(this.listsValue))
  }

  async select(input) {
    this.calls.push({ name: 'select', input })
    if (this.failSelect) {
      const error = new Error(this.failSelect.message)
      error.status = this.failSelect.status
      error.code = this.failSelect.code
      throw error
    }
    const chosen = this.listsValue.lists.find(
      (list) => list.href === input.list_href,
    )
    this.statusValue.setting.enabled = true
    this.statusValue.setting.list_href = chosen.href
    this.statusValue.setting.list_name = chosen.display_name
    this.statusValue.setting.setting_version = input.expected_version + 1
    this.listsValue.enabled = true
    return {
      ok: true,
      enabled: true,
      list_href: chosen.href,
      list_name: chosen.display_name,
      setting_version: input.expected_version + 1,
    }
  }

  async sync(requestId) {
    this.calls.push({ name: 'sync', requestId })
    if (this.syncResult) return this.syncResult
    return {
      state: 'ok',
      pulled_created: 0,
      pulled_updated: 0,
      pushed_created: 1,
      pushed_updated: 0,
      reattached: 0,
      remote_missing: 0,
      conflicts: 0,
      remote_kept_local: 0,
    }
  }

  async disable(input) {
    this.calls.push({ name: 'disable', input })
    this.statusValue.setting.enabled = false
    if (input.clear_credentials) {
      this.statusValue.credential = { configured: false }
    }
    this.statusValue.setting.setting_version = input.expected_version + 1
    return {
      ok: true,
      enabled: false,
      setting_version: input.expected_version + 1,
      credentials_cleared: input.clear_credentials === true,
    }
  }
}

function loadTodoSyncModule() {
  const cache = new ScriptCache()
  const file = path.join(d1Dir, 'todoSync.ts')
  const clientFile = resolveTsFile('./client', file)
  const todoSync = cache.load(file)
  const client = cache.load(clientFile)
  return { todoSync, client }
}

async function main() {
  const { todoSync } = await (async () => {
    return { todoSync: loadTodoSyncModule().todoSync }
  })()

  // -- store: default off, connect, explicit enable, sync, disable -------
  {
    const api = new FakeSyncApi()
    const store = todoSync.createTodoSyncStore(api)
    await store.loadStatus()
    await flush()
    assert.equal(store.state.status.setting.enabled, false)
    assert.equal(store.connected.value, false)
    ok('status defaults to off and unconfigured')

    const sent = await store.connect({
      url: 'https://cloud.example.com/',
      username: 'teacher',
      password: 'app-secret-1',
    })
    assert.equal(sent, true)
    assert.equal(api.connected.password, 'app-secret-1')
    assert.equal(store.state.status.setting.server_url, 'https://cloud.example.com/')
    // The password never lands in the store state.
    assert.ok(!JSON.stringify(store.state).includes('app-secret-1'))
    ok('connect sends the password once and never keeps it in state')

    api.listsValue = {
      lists: [
        { href: '/remote.php/dav/calendars/teacher/tasks/', display_name: '工作清单', supports_vtodo: true },
        { href: '/remote.php/dav/calendars/teacher/personal/', display_name: '个人', supports_vtodo: true },
      ],
      selected: null,
      enabled: false,
    }
    await store.loadLists()
    assert.equal(store.state.lists.length, 2)

    const enabled = await store.selectList('/remote.php/dav/calendars/teacher/tasks/')
    assert.equal(enabled, true)
    assert.equal(store.enabled.value, true)
    assert.match(store.state.notice, /双向同步所选清单/)
    ok('selecting a list is the explicit two-way enable')

    await store.syncNow()
    assert.match(store.state.notice, /已上传新增 1 项/)
    ok('a manual sync reports the fixed summary text')

    await store.disable(false)
    assert.equal(store.enabled.value, false)
    await store.disable(true)
    assert.equal(store.state.status.credential.configured, false)
    ok('disable stops the linkage; the clear option forgets the account')
  }

  // -- store: fixed error projection --------------------------------------
  {
    const { todoSync: syncModule, client } = loadTodoSyncModule()
    const api = new FakeSyncApi()
    api.failConnect = new client.ApiError(
      401,
      'Nextcloud 用户名或密码不正确，或没有访问权限',
      'SYNC_AUTH_FAILED',
    )
    const store = syncModule.createTodoSyncStore(api)
    await store.connect({
      url: 'https://cloud.example.com/',
      username: 'teacher',
      password: 'wrong',
    })
    assert.match(store.state.error, /用户名或密码不正确/)
    ok('a fixed transport code projects to its teacher-facing text')
  }

  // -- result text mapping -------------------------------------------------
  {
    const text = todoSync.todoSyncResultText({
      state: 'ok',
      pulled_created: 1,
      pulled_updated: 1,
      pushed_created: 1,
      pushed_updated: 1,
      conflicts: 1,
      remote_missing: 1,
    })
    assert.match(text, /从远端新增 1/)
    assert.match(text, /远端更新 1/)
    assert.match(text, /已上传新增 1/)
    assert.match(text, /已上传修改 1/)
    assert.match(text, /双方都修改 1 项（未覆盖）/)
    assert.match(text, /远端已删除 1 项（本地保留）/)
    assert.equal(
      todoSync.todoSyncResultText({ state: 'disabled' }),
      '双向同步未开启',
    )
    assert.equal(
      todoSync.todoSyncResultText({ state: 'ok' }),
      '本次同步没有变化',
    )
    ok('sync summaries use the fixed counting text')
  }

  // -- workbench status helpers -------------------------------------------
  {
    assert.equal(todoSync.workbenchSyncLabel(), '')
    todoSync.rememberWorkbenchSyncStatus({
      setting: {
        configured: true,
        enabled: true,
        server_url: 'https://cloud.example.com/',
        username: 'teacher',
        list_href: '/x/',
        list_name: '工作清单',
        setting_version: 2,
        last_sync_at: '2026-11-26 10:00:00',
        last_result: null,
      },
      credential: { configured: true, password_available: true },
    })
    const label = todoSync.workbenchSyncLabel()
    assert.match(label, /Nextcloud/)
    assert.match(label, /工作清单/)
    assert.match(label, /上次同步/)
    ok('the workbench status line names the list and last sync only')
  }

  // -- SFC source checks ---------------------------------------------------
  const panelFile = path.join(d1Dir, 'views', 'TodoSyncPanel.vue')
  const workbenchFile = path.join(d1Dir, 'views', 'WorkbenchTodoPanel.vue')
  const panelSource = fs.readFileSync(panelFile, 'utf8')
  const workbenchSource = fs.readFileSync(workbenchFile, 'utf8')

  for (const [name, source] of [
    ['TodoSyncPanel', panelSource],
    ['WorkbenchTodoPanel', workbenchSource],
  ]) {
    const { descriptor } = parse(source, { filename: name })
    const script = compileScript(descriptor, { id: name })
    const compiled = compileTemplate({
      source: descriptor.template.content,
      filename: name,
      id: name,
    })
    assert.equal(compiled.errors.length, 0, String(compiled.errors))
    assert.ok(script.content, `${name} script compiles`)
    assert.equal(source.includes('v-html'), false)
    ok(`${name} compiles without template errors and never uses v-html`)
  }

  const hooks = [
    'data-d1="todo-sync-panel"',
    'data-d1="todo-sync-url"',
    'data-d1="todo-sync-username"',
    'data-d1="todo-sync-password"',
    'data-d1="todo-sync-connect"',
    'data-d1="todo-sync-enable"',
    'data-d1="todo-sync-run"',
    'data-d1="todo-sync-disable"',
    'data-d1="todo-sync-disable-clear"',
    'data-d1="todo-sync-error"',
    'data-d1="todo-sync-privacy-note"',
  ]
  for (const hook of hooks) {
    assert.ok(panelSource.includes(hook), `missing ${hook}`)
  }
  assert.ok(panelSource.includes('双向同步所选清单（新增、编辑和完成）'))
  assert.ok(panelSource.includes('删除不会在两端传播'))
  assert.ok(workbenchSource.includes('data-d1="todo-sync-status"'))
  assert.ok(workbenchSource.includes('data-d1="todo-sync-now"'))
  ok('the explicit two-way choice, no-delete wording and hooks are pinned')

  console.log(`\n${passed} passed`)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
