/**
 * B2 host-adapter integration checks (Node, no WebView2).
 *
 * The fake ``window.pywebview.api`` mirrors the snake_case host replies; the
 * adapter must expose only camelCase opaque ids/DTOs, throw allowlisted host
 * errors, and never resend a start/confirm side effect.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { parse, compileTemplate } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'
import { createBackupRestoreHost } from './bridge.ts'

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function installApi(api) {
  globalThis.window = { pywebview: { api } }
}

function baseStatus(overrides = {}) {
  return {
    request_id: 'req-1',
    operation_id: 'op-1',
    generation: 3,
    kind: 'restore',
    phase: 'preview',
    progress: null,
    preview: {
      package_name: 'sample.kgmbackup',
      created_at: '2026-10-31T00:00:00Z',
      app_version: '0.1.0',
      source_revision: '0005',
      preview_id: 'preview-token',
      profile_name: '王老师',
      class_name: '中一班',
      term_names: ['上学期', '下学期'],
      counts: { daily_plans: 4, observations: 5, assets: 6 },
      credential_configured: true,
      credential_ready: false,
    },
    protection: {
      display_text:
        '恢复前保护副本：D:\\备份\\保护副本。自动保留，不会自动删除。',
    },
    error: null,
    cancel_requested: false,
    stale: false,
    reopened: false,
    ...overrides,
  }
}

// --- startup / dialogs ------------------------------------------------------
{
  const calls = []
  installApi({
    async get_startup_maintenance_state() {
      return { state: 'ready' }
    },
    async choose_backup_target() {
      calls.push('backup-dialog')
      return {
        ok: true,
        target: { target_id: 'target-1', display_name: '我的备份.kgmbackup' },
      }
    },
    async choose_restore_source() {
      calls.push('restore-dialog')
      return {
        ok: true,
        selection: {
          selection_id: 'selection-1',
          display_name: '旧备份.kgmbackup',
          encrypted: true,
        },
      }
    },
  })
  const host = createBackupRestoreHost()
  assert.deepEqual(await host.getStartupMaintenanceState(), { state: 'ready' })
  assert.deepEqual(await host.chooseBackupTarget(), {
    ok: true,
    target: { targetId: 'target-1', displayName: '我的备份.kgmbackup' },
  })
  assert.deepEqual(await host.chooseRestoreSource(), {
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: '旧备份.kgmbackup',
      encrypted: true,
    },
  })
  assert.deepEqual(calls, ['backup-dialog', 'restore-dialog'])
  ok('dialogs expose only opaque ids and display names')
}

{
  installApi({
    async choose_backup_target() {
      return { ok: false, canceled: true }
    },
    async choose_restore_source() {
      return { ok: false, canceled: true }
    },
  })
  const host = createBackupRestoreHost()
  assert.deepEqual(await host.chooseBackupTarget(), { ok: false, canceled: true })
  assert.deepEqual(await host.chooseRestoreSource(), {
    ok: false,
    canceled: true,
  })
  ok('dialog cancellation is honest, not an error')
}

// --- start / verify / confirm payloads and idempotent refs ------------------
{
  const requests = []
  installApi({
    async start_backup(payload) {
      requests.push(['backup', payload])
      return { request_id: payload.request_id, operation_id: 'op-b', generation: 1 }
    },
    async start_restore_verify(payload) {
      requests.push(['verify', payload])
      return { request_id: payload.request_id, operation_id: 'op-r', generation: 2 }
    },
    async confirm_restore(payload) {
      requests.push(['confirm', payload])
      return { request_id: payload.request_id, operation_id: 'op-r', generation: 3 }
    },
  })
  const host = createBackupRestoreHost()
  assert.deepEqual(
    await host.startBackup({
      requestId: 'req-b',
      targetId: 'target-1',
      password: 'secret',
      explicitPlaintext: false,
    }),
    { requestId: 'req-b', operationId: 'op-b', generation: 1 },
  )
  assert.deepEqual(
    await host.startRestoreVerify({
      requestId: 'req-r',
      selectionId: 'selection-1',
      password: null,
    }),
    { requestId: 'req-r', operationId: 'op-r', generation: 2 },
  )
  assert.deepEqual(
    await host.confirmRestore({
      requestId: 'req-c',
      operationId: 'op-r',
      generation: 2,
      confirmationToken: 'preview-token',
    }),
    { requestId: 'req-c', operationId: 'op-r', generation: 3 },
  )
  assert.deepEqual(requests, [
    [
      'backup',
      {
        request_id: 'req-b',
        target_id: 'target-1',
        password: 'secret',
        explicit_plaintext: false,
      },
    ],
    ['verify', { request_id: 'req-r', selection_id: 'selection-1', password: null }],
    [
      'confirm',
      {
        request_id: 'req-c',
        operation_id: 'op-r',
        generation: 2,
        confirmation_token: 'preview-token',
      },
    ],
  ])
  ok('start/verify/confirm convert camelCase input exactly once')
}

{
  installApi({
    async start_backup() {
      return { error: { code: 'REQUEST_CONFLICT', message: '同一请求 ID 对应了不同操作' } }
    },
    async confirm_restore() {
      return { error: { code: 'PREVIEW_STALE', message: '预览已失效，请重新校验' } }
    },
  })
  const host = createBackupRestoreHost()
  await assert.rejects(
    () =>
      host.startBackup({
        requestId: 'req',
        targetId: 't',
        password: null,
        explicitPlaintext: true,
      }),
    /REQUEST_CONFLICT/,
  )
  await assert.rejects(
    () =>
      host.confirmRestore({
        requestId: 'req',
        operationId: 'op',
        generation: 1,
        confirmationToken: 'x',
      }),
    /PREVIEW_STALE/,
  )
  ok('host error DTOs surface as allowlisted codes, not raw payloads')
}

// --- query / cancel ---------------------------------------------------------
{
  const lookups = []
  installApi({
    async query_maintenance(payload) {
      lookups.push(payload)
      if ('request_id' in payload && payload.request_id === 'missing') {
        return { state: 'unknown' }
      }
      if ('operation_id' in payload && payload.generation === 99) {
        return { state: 'unknown' }
      }
      return { state: 'found', status: baseStatus() }
    },
    async cancel_maintenance(payload) {
      lookups.push(payload)
      return { accepted: false, state: 'too_late' }
    },
  })
  const host = createBackupRestoreHost()
  const byRequest = await host.queryMaintenance({ requestId: 'req-1' })
  assert.equal(byRequest.state, 'found')
  assert.equal(byRequest.status.requestId, 'req-1')
  assert.equal(byRequest.status.operationId, 'op-1')
  assert.equal(byRequest.status.generation, 3)
  assert.equal(byRequest.status.preview.displayName, 'sample.kgmbackup')
  assert.equal(byRequest.status.preview.confirmationToken, 'preview-token')
  assert.equal(byRequest.status.preview.termLabel, '上学期、下学期')
  assert.deepEqual(byRequest.status.preview.counts, {
    plans: 4,
    observations: 5,
    photos: 6,
    others: 0,
  })
  assert.equal(byRequest.status.preview.credentialAvailability, 'needs_reentry')
  assert.equal(
    byRequest.status.protection.displayText,
    '恢复前保护副本：D:\\备份\\保护副本。自动保留，不会自动删除。',
  )
  assert.deepEqual(
    await host.queryMaintenance({ operationId: 'op-1', generation: 3 }),
    byRequest,
  )
  assert.deepEqual(await host.queryMaintenance({ requestId: 'missing' }), {
    state: 'unknown',
  })
  assert.deepEqual(
    await host.queryMaintenance({ operationId: 'op-1', generation: 99 }),
    { state: 'unknown' },
  )
  assert.deepEqual(await host.cancelMaintenance({ requestId: 'req-1' }), {
    accepted: false,
    state: 'too_late',
  })
  assert.deepEqual(lookups, [
    { request_id: 'req-1' },
    { operation_id: 'op-1', generation: 3 },
    { request_id: 'missing' },
    { operation_id: 'op-1', generation: 99 },
    { request_id: 'req-1' },
  ])
  ok('query/cancel use requestId or operationId+generation without resending side effects')
}

// --- error / protection / reopen text --------------------------------------
{
  installApi({
    async query_maintenance() {
      return {
        state: 'found',
        status: baseStatus({
          phase: 'error',
          preview: null,
          protection: {
            display_text:
              '恢复前保护副本：D:\\保护\\副本。自动保留，不会自动删除。',
          },
          error: {
            code: 'REOPEN_FAILED',
            message: '资料已恢复，重新打开失败，请重启应用',
            committed: true,
            next_action: 'restart_app',
          },
        }),
      }
    },
  })
  const host = createBackupRestoreHost()
  const result = await host.queryMaintenance({ requestId: 'req-1' })
  assert.equal(result.status.phase, 'error')
  assert.equal(result.status.error.code, 'REOPEN_FAILED')
  assert.equal(result.status.error.committed, true)
  assert.equal(result.status.error.nextAction, 'restart_app')
  assert.equal(
    result.status.error.message,
    '资料已恢复，重新打开失败，请重启应用',
  )
  assert.match(result.status.protection.displayText, /自动保留，不会自动删除。$/)
  ok('reopen failure keeps exact text, committed flag and protection location')
}

// --- unavailable host / old host ------------------------------------------
{
  globalThis.window = {}
  const host = createBackupRestoreHost()
  await assert.rejects(
    () =>
      host.startBackup({
        requestId: 'req',
        targetId: 't',
        password: null,
        explicitPlaintext: true,
      }),
    /HOST_UNAVAILABLE/,
  )
  assert.deepEqual(await host.getStartupMaintenanceState(), { state: 'ready' })
  assert.deepEqual(await host.queryMaintenance({ requestId: 'req' }), {
    state: 'unavailable',
  })
  assert.deepEqual(await host.cancelMaintenance({ requestId: 'req' }), {
    accepted: false,
    state: 'unknown',
  })
  ok('missing/old host degrades without inventing success')
}


// --- WebDAV downloaded status through the real adapter ---------------------
{
  installApi({
    async query_maintenance() {
      return {
        state: 'found',
        status: {
          ...baseStatus({
            request_id: 'req-webdav-download',
            operation_id: 'op-webdav-download',
            generation: 4,
            phase: 'downloaded',
            preview: null,
            protection: null,
          }),
          selection: {
            selection_id: 'webdav-selection-1',
            display_name: 'kgm-backup-20261119T120000Z-' + 'a'.repeat(32) + '.kgmbackup',
            encrypted: true,
          },
        },
      }
    },
  })
  const host = createBackupRestoreHost()
  const result = await host.queryMaintenance({ requestId: 'req-webdav-download' })
  assert.equal(result.state, 'found')
  assert.equal(result.status.phase, 'downloaded')
  assert.deepEqual(result.status.selection, {
    selectionId: 'webdav-selection-1',
    displayName: 'kgm-backup-20261119T120000Z-' + 'a'.repeat(32) + '.kgmbackup',
    encrypted: true,
  })
  // Still opaque: no local path/credential leaks into the panel DTO.
  assert.equal('path' in result.status.selection, false)
  ok('real adapter maps the WebDAV downloaded selection hand-off')
}

// --- existing-shell wiring (source-level integration) ----------------------
{
  const fs = await import('node:fs')
  const path = await import('node:path')
  const { fileURLToPath } = await import('node:url')
  const d1Dir = path.dirname(fileURLToPath(import.meta.url))
  const read = (name) => fs.readFileSync(path.join(d1Dir, name), 'utf8')
  const app = read('App.vue')
  const settings = read('views/SettingsView.vue')
  const setup = read('views/SetupView.vue')
  const bridge = read('bridge.ts')

  assert.match(app, /<BackupRestorePanel/)
  assert.match(app, /:host="maintenanceHost"/)
  assert.match(app, /@busy="maintenanceBusy = \$event"/)
  assert.match(app, /@blocking="maintenanceBlocking = \$event"/)
  assert.match(app, /@recovered="onMaintenanceRecovered"/)
  assert.match(app, /completion\.target === 'webdav'/)
  assert.match(app, /WebDAV 备份已创建/)
  assert.match(app, /完整本地备份已创建/)
  assert.match(app, /maintenanceLocked/)
  assert.match(app, /page_business_ready\?\.\(/)
  assert.match(app, /bootstrapInfo\.maintenance_notice/)
  assert.match(app, /maintenanceNotice\.value = bootstrapNotice/)
  assert.match(app, /data-d1="restore-notice"/)
  // Both P06 entries are wired to the same panel.
  assert.equal((app.match(/@open-maintenance="openMaintenance"/g) ?? []).length, 2)
  assert.match(app, /function openMaintenance\(\): void/)
  assert.match(app, /const draft = currentBlockingDraft\(\)/)
  assert.match(settings, /data-d1="open-backup-restore"/)
  assert.match(settings, /emit\('open-maintenance'\)/)
  assert.match(setup, /data-d1="setup-restore"/)
  assert.match(setup, /从备份恢复/)
  assert.match(setup, /WebDAV/)
  assert.match(setup, /emit\('open-maintenance'\)/)
  assert.match(bridge, /export function createBackupRestoreHost/)
  assert.match(bridge, /page_business_ready\?:/)
  assert.match(bridge, /maintenance_notice\?: string/)
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(d1Dir, '..', '..', 'package.json'), 'utf8'),
  )
  assert.match(packageJson.scripts['test:d1'], /d1\.backup-ui\.test\.mjs/)
  ok('existing shell wires both P06 entries, the business-ready ack and the new-page notice')
}


// --- real App.vue template render: notice must not replace the page chain ---
{
  const d1Dir = path.dirname(fileURLToPath(import.meta.url))
  const appSource = fs.readFileSync(path.join(d1Dir, 'App.vue'), 'utf8')
  const { descriptor } = parse(appSource)
  assert.ok(descriptor.template, 'App.vue template missing')
  const compiled = compileTemplate({
    source: descriptor.template.content,
    filename: 'App.vue',
    id: 'app-notice-test',
    compilerOptions: {
      mode: 'module',
      isTS: true,
      expressionPlugins: ['typescript'],
    },
  })
  assert.equal(compiled.errors.length, 0, String(compiled.errors))
  const js = ts.transpileModule(compiled.code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText
  const stubs = new Map()
  const resolveComponent = (name) => {
    if (!stubs.has(name)) stubs.set(name, { __name: name })
    return stubs.get(name)
  }
  const Vue = { ...vue, resolveComponent }
  const module = { exports: {} }
  const require = createRequire(import.meta.url)
  new Function('require', 'module', 'exports', js)(
    (name) => (name === 'vue' ? Vue : require(name)),
    module,
    module.exports,
  )
  const render = module.exports.render
  assert.equal(typeof render, 'function')

  function vnodeNames(vnode, out = []) {
    if (!vnode || typeof vnode !== 'object') return out
    const type = vnode.type
    const name = typeof type === 'string' ? type : type?.__name || type?.name
    if (name) out.push(name)
    if (Array.isArray(vnode.children)) {
      for (const child of vnode.children) {
        if (child && typeof child === 'object') vnodeNames(child, out)
      }
    }
    return out
  }

  function hasDataD1(vnode, marker) {
    if (!vnode || typeof vnode !== 'object') return false
    if (vnode.props && vnode.props['data-d1'] === marker) return true
    if (Array.isArray(vnode.children)) {
      return vnode.children.some(
        (child) => child && typeof child === 'object' && hasDataD1(child, marker),
      )
    }
    return false
  }

  const base = {
    bootState: 'ready',
    bootError: '',
    maintenanceNotice: '',
    view: { name: 'workbench' },
    context: {},
    closeLocked: false,
  }
  const renderWith = (state) => {
    const ctx = new Proxy(state, {
      get: (target, key) => (key in target ? target[key] : () => undefined),
    })
    return render(ctx, [])
  }

  const notice = '恢复前保护副本：D:\保护\副本。自动保留，不会自动删除。'

  // A normal workbench remains rendered while the notice is visible.
  const workbench = vnodeNames(
    renderWith({ ...base, maintenanceNotice: notice }),
  )
  assert.ok(workbench.includes('el-alert'))
  assert.ok(workbench.includes('WorkbenchView'))
  assert.ok(!workbench.includes('SetupView'))
  assert.ok(!workbench.includes('el-result'))

  // No notice: the workbench is unchanged and no alert is invented.
  const noNotice = vnodeNames(renderWith(base))
  assert.ok(noNotice.includes('WorkbenchView'))
  assert.ok(!noNotice.includes('el-alert'))

  // Setup (first run) shows the notice and the setup view together.
  const setup = vnodeNames(
    renderWith({
      ...base,
      bootState: 'uninitialized',
      maintenanceNotice: notice,
      view: { name: 'setup' },
      context: null,
    }),
  )
  assert.ok(setup.includes('el-alert'))
  assert.ok(setup.includes('SetupView'))
  assert.ok(!setup.includes('WorkbenchView'))

  // Connecting/error keep their own branch and never render a stale notice.
  const connecting = renderWith({
    ...base,
    bootState: 'connecting',
    maintenanceNotice: notice,
  })
  assert.ok(hasDataD1(connecting, 'connecting'))
  assert.ok(!vnodeNames(connecting).includes('el-alert'))
  assert.ok(!vnodeNames(connecting).includes('WorkbenchView'))
  assert.ok(!vnodeNames(connecting).includes('SetupView'))

  const error = vnodeNames(
    renderWith({
      ...base,
      bootState: 'error',
      bootError: 'synthetic',
      maintenanceNotice: notice,
    }),
  )
  assert.ok(error.includes('el-result'))
  assert.ok(!error.includes('el-alert'))
  assert.ok(!error.includes('WorkbenchView'))

  ok('App.vue notice renders with the page chain, not instead of it')
}

// --- WebDAV bridge adapter -------------------------------------------------
{
  const calls = []
  installApi({
    async webdav_get_config() {
      return {
        available: true,
        config: {
          configured: true,
          url: 'https://dav.example/backup/',
          username: 'teacher',
          password_available: true,
        },
      }
    },
    async save_webdav_config(payload) {
      calls.push({ name: 'save', payload })
      return {
        ok: true,
        config: {
          configured: true,
          url: payload.url,
          username: payload.username,
          password_available: true,
        },
      }
    },
    async webdav_list_versions() {
      return {
        versions: [
          {
            name: 'kgm-backup-20261119T120000Z-' + 'a'.repeat(32) + '.kgmbackup',
            size: 2048,
            modified_at: 'Wed, 19 Nov 2026 12:00:00 GMT',
          },
        ],
        endpoint_fingerprint: 'fingerprint-1',
        config: { configured: true },
      }
    },
    async start_webdav_backup(payload) {
      calls.push({ name: 'backup', payload })
      return { request_id: payload.request_id, operation_id: 'op-wb', generation: 1 }
    },
    async start_webdav_download(payload) {
      calls.push({ name: 'download', payload })
      return { request_id: payload.request_id, operation_id: 'op-wd', generation: 2 }
    },
    async release_webdav_selection(payload) {
      calls.push({ name: 'release', payload })
      return { released: true }
    },
  })
  const { createWebdavHost } = await import('./backupMaintenance.ts')
  const webdav = createWebdavHost()
  const config = await webdav.getWebdavConfig()
  assert.deepEqual(config, {
    available: true,
    config: {
      configured: true,
      url: 'https://dav.example/backup/',
      username: 'teacher',
      passwordAvailable: true,
    },
  })
  const saved = await webdav.saveWebdavConfig({
    url: 'https://dav.example/backup/',
    username: 'teacher',
    password: 's3cret',
  })
  assert.equal(saved.ok, true)
  assert.deepEqual(calls[0], {
    name: 'save',
    payload: {
      url: 'https://dav.example/backup/',
      username: 'teacher',
      password: 's3cret',
    },
  })
  const versions = await webdav.listWebdavVersions()
  assert.equal(versions.endpointFingerprint, 'fingerprint-1')
  assert.equal(versions.versions[0].size, 2048)
  assert.equal(versions.versions[0].modifiedAt, 'Wed, 19 Nov 2026 12:00:00 GMT')

  const backup = await webdav.startWebdavBackup({
    requestId: 'req-wb',
    password: 'pw',
  })
  assert.deepEqual(backup, {
    requestId: 'req-wb',
    operationId: 'op-wb',
    generation: 1,
  })
  assert.equal(calls.at(-1).payload.explicit_plaintext, false)

  const download = await webdav.startWebdavDownload({
    requestId: 'req-wd',
    versionName: 'kgm-backup-20261119T120000Z-' + 'a'.repeat(32) + '.kgmbackup',
    endpointFingerprint: 'fingerprint-1',
  })
  assert.deepEqual(download, {
    requestId: 'req-wd',
    operationId: 'op-wd',
    generation: 2,
  })
  assert.equal(calls.at(-1).payload.endpoint_fingerprint, 'fingerprint-1')
  assert.deepEqual(await webdav.releaseWebdavSelection('sel-1'), {
    released: true,
  })
  assert.deepEqual(calls.at(-1), {
    name: 'release',
    payload: { selection_id: 'sel-1' },
  })
  ok('WebDAV adapter maps opaque DTOs and never sends plaintext uploads')
}

{
  installApi({
    async webdav_list_versions() {
      return {
        error: {
          code: 'WEBDAV_AUTH_FAILED',
          message: 'WebDAV 用户名或密码不正确，或没有访问权限',
        },
      }
    },
  })
  const { createWebdavHost, WebdavHostError } = await import('./backupMaintenance.ts')
  const webdav = createWebdavHost()
  await assert.rejects(
    () => webdav.listWebdavVersions(),
    (err) =>
      err instanceof WebdavHostError &&
      err.code === 'WEBDAV_AUTH_FAILED' &&
      /用户名或密码/.test(err.message),
  )
  ok('WebDAV host errors keep the coded teacher-facing message')
}

{
  globalThis.window = {}
  const { createWebdavHost } = await import('./backupMaintenance.ts')
  const webdav = createWebdavHost()
  assert.deepEqual(await webdav.getWebdavConfig(), {
    available: false,
    config: { configured: false, passwordAvailable: false },
  })
  await assert.rejects(
    () =>
      webdav.startWebdavBackup({ requestId: 'r', password: 'pw' }),
    (err) => err.code === 'WEBDAV_UNAVAILABLE',
  )
  assert.deepEqual(await webdav.releaseWebdavSelection('sel'), {
    released: false,
  })
  ok('missing WebDAV host degrades without inventing success')
}

console.log(`OK B2 backup host adapter (${passed} groups)`)
