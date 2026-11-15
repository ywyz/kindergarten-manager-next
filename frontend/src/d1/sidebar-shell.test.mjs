/**
 * Sidebar shell regression: real Settings/Collaboration SFC templates render
 * their existing page navigation into the stable LEFT target, while hidden
 * sections never leak a second page navigation. Standalone rendering keeps the
 * local left fallback. The theme checks the vertical rail/no-top-nav contract.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: {
      id: 'c1',
      name: '中一班',
      grade: 'middle',
      header_teacher_names: ['李老师'],
      caregiver_name: '张阿姨',
    },
    term: {
      id: 't1',
      name: '秋季学期',
      start_date: '2026-09-01',
      end_date: '2027-01-31',
    },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [
      {
        id: 't1',
        name: '秋季学期',
        start_date: '2026-09-01',
        end_date: '2027-01-31',
        current_calendar_revision_id: 'r1',
      },
    ],
  }
}

class Harness {
  constructor() {
    this.moduleCache = new Map()
    this.componentStubs = new Map()
    this.componentCounts = new Map()
    this.window = {}
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => { harness.window[key] = value; return true },
      has: () => true,
    })
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Number,
      Object,
      Array,
      String,
      Promise,
      Map,
      Set,
      setTimeout,
      clearTimeout,
      crypto: { randomUUID: () => 'uuid-sidebar-shell' },
      window: windowProxy,
      document: undefined,
    }
  }

  _require(spec, fromFile) {
    if (spec === 'vue') return vue
    if (spec === 'element-plus') return { ElMessage: () => undefined }
    if (spec === '../client') {
      return {
        ApiError: class ApiError extends Error {},
        apiGet: async () => contextFixture(),
        apiPost: async () => ({}),
        apiPatch: async () => ({}),
        pathSegment: (value) => encodeURIComponent(String(value)),
      }
    }
    if (spec === '../collaboration') {
      return {
        createCollaborationApi: () => ({
          status: async () => ({
            configured: true,
            connected: false,
            teacher: null,
            message: '',
          }),
          classes: async () => [],
          membership: async () => null,
          classmates: async () => [],
          ownConfig: async () => ({
            class_id: '',
            config_version: 0,
            payload: { locations: [], game_scope: null, guidance: null },
          }),
          getPromotion: async () => ({ terms: [] }),
        }),
        collaborationErrorMessage: (_error, fallback) => fallback,
        collaborationWriteIndeterminate: () => false,
        isCollaborationConflictError: () => false,
        isCollaborationResubmitUncommittedError: () => false,
        isCollaborationSessionInvalidError: () => false,
        reconcilePromotionResult: () => ({ accepted: false }),
      }
    }
    if (spec.endsWith('.vue')) {
      let stub = this.componentStubs.get(spec)
      if (!stub) {
        const harness = this
        stub = {
          name: path.basename(spec, '.vue'),
          setup: () => {
            harness.componentCounts.set(
              spec,
              (harness.componentCounts.get(spec) ?? 0) + 1,
            )
            return () => vue.h('div', { 'data-stub': spec })
          },
        }
        this.componentStubs.set(spec, stub)
      }
      return { __esModule: true, default: stub }
    }
    const base = path.resolve(path.dirname(fromFile), spec)
    const file = [base, `${base}.ts`, path.join(base, 'index.ts')].find(
      (candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
    )
    if (!file) throw new Error(`cannot resolve ${spec} from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
      fileName: file,
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = file
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename: file })
    } finally {
      this._currentFile = previous
    }
    this.moduleCache.set(file, module.exports)
    return module.exports
  }

  load(relativePath, props = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    assert.deepEqual(parse(source, { filename: file }).errors, [])
    const script = compileScript(descriptor, { id: relativePath })
    const template = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: relativePath,
      compilerOptions: {
        mode: 'function',
        bindingMetadata: script.bindings,
        isTS: true,
        expressionPlugins: ['typescript'],
      },
    })
    assert.deepEqual(template.errors, [], String(template.errors))
    const js = ts.transpileModule(script.content, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
      fileName: file,
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = file
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename: file })
    } finally {
      this._currentFile = previous
    }
    const component = module.exports.default
    const templateModule = { exports: {} }
    const templateJs = ts.transpileModule(template.code, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText
    const render = new Function('Vue', 'require', 'module', 'exports', templateJs)(
      vue,
      (name) => {
        if (name === 'vue') return vue
        throw new Error(`unexpected template require ${name}`)
      },
      templateModule,
      templateModule.exports,
    )
    component.render = render
    return { component, props }
  }

  async render(relativePath, props = {}) {
    const { component } = this.load(relativePath, props)
    const app = vue.createSSRApp({
      render: () => vue.h(component, props),
    })
    const elements = [
      'el-alert', 'el-button', 'el-card', 'el-tag', 'el-table',
      'el-table-column', 'el-dialog', 'el-input', 'el-select', 'el-option',
      'el-date-picker', 'el-radio-group', 'el-radio-button', 'el-checkbox',
      'el-result', 'el-empty', 'el-progress', 'el-form', 'el-form-item',
    ]
    for (const name of elements) {
      app.component(name, {
        name,
        setup(_, { attrs, slots }) {
          return () => vue.h('div', { ...attrs, 'data-stub-el': name }, [
            slots.default?.(),
            slots.header?.(),
            slots.footer?.(),
          ])
        },
      })
    }
    app.directive('loading', {})
    const context = {}
    const html = await renderToString(app, context)
    return { html, teleports: context.teleports ?? {} }
  }

  async miniRender(relativePath, initialProps = {}) {
    const { component } = this.load(relativePath, initialProps)
    const props = vue.reactive({ ...initialProps })
    const mini = createMiniRenderer()
    const app = mini.renderer.createApp({
      render: () => vue.h(component, props),
    })
    const elements = [
      'el-alert', 'el-button', 'el-card', 'el-tag', 'el-table',
      'el-table-column', 'el-dialog', 'el-input', 'el-select', 'el-option',
      'el-date-picker', 'el-radio-group', 'el-radio-button', 'el-checkbox',
      'el-result', 'el-empty', 'el-progress', 'el-form', 'el-form-item',
    ]
    for (const name of elements) {
      app.component(name, {
        name,
        setup(_, { attrs, slots }) {
          return () => vue.h('div', { ...attrs, 'data-stub-el': name }, [
            slots.default?.(),
            slots.header?.(),
            slots.footer?.(),
          ])
        },
      })
    }
    app.directive('loading', {})
    app.mount(mini.root)
    await vue.nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await vue.nextTick()
    return { app, props, harness: this, ...mini }
  }
}

function createMiniRenderer() {
  const makeElement = (tag) => ({
    kind: 'element',
    tag,
    props: {},
    style: {},
    children: [],
    parent: null,
    text: '',
  })
  const makeText = (text) => ({
    kind: 'text',
    tag: '#text',
    props: {},
    style: {},
    children: [],
    parent: null,
    text,
  })
  const makeComment = (text) => ({
    kind: 'comment',
    tag: '#comment',
    props: {},
    style: {},
    children: [],
    parent: null,
    text,
  })

  function remove(child) {
    const parent = child.parent
    if (!parent) return
    const index = parent.children.indexOf(child)
    if (index >= 0) parent.children.splice(index, 1)
    child.parent = null
  }

  function insert(child, parent, anchor = null) {
    if (child.parent) remove(child)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, child)
    else parent.children.push(child)
    child.parent = parent
  }

  const root = makeElement('root')
  const target = makeElement('div')
  target.props.id = 'd1-page-navigation'
  insert(target, root)
  const targetMap = new Map([['#d1-page-navigation', target]])

  const renderer = vue.createRenderer({
    patchProp(el, key, _prev, next) {
      el.props[key] = next
    },
    insert,
    remove,
    createElement: makeElement,
    createText: makeText,
    createComment: makeComment,
    setText(node, text) {
      node.text = text
    },
    setElementText(el, text) {
      el.text = text
      el.children = []
    },
    parentNode(node) {
      return node.parent
    },
    nextSibling(node) {
      if (!node.parent) return null
      const index = node.parent.children.indexOf(node)
      return index >= 0 ? node.parent.children[index + 1] ?? null : null
    },
    querySelector(selector) {
      return targetMap.get(selector) ?? null
    },
    insertStaticContent(content, parent, anchor, _isSVG, _start, _end) {
      const node = makeText(String(content))
      insert(node, parent, anchor)
      return [node, node]
    },
  })

  function walk(node, visit) {
    if (!node) return
    visit(node)
    for (const child of [...node.children]) walk(child, visit)
  }
  function classesOf(node) {
    const value = node?.props?.class
    if (typeof value === 'string') return value
    if (Array.isArray(value)) return value.join(' ')
    if (value && typeof value === 'object') {
      return Object.entries(value)
        .filter(([, enabled]) => enabled)
        .map(([name]) => name)
        .join(' ')
    }
    return ''
  }
  function findAttr(node, attr, value) {
    let found = null
    walk(node, (item) => {
      if (!found && item.props?.[attr] === value) found = item
    })
    return found
  }
  function findClass(node, name) {
    let found = null
    walk(node, (item) => {
      if (!found && classesOf(item).split(/\s+/).includes(name)) found = item
    })
    return found
  }
  function contains(ancestor, node) {
    let cursor = node
    while (cursor) {
      if (cursor === ancestor) return true
      cursor = cursor.parent
    }
    return false
  }
  function findLocalAttr(node, excluded, attr, value) {
    let found = null
    walk(node, (item) => {
      if (!found && !contains(excluded, item) && item.props?.[attr] === value) {
        found = item
      }
    })
    return found
  }
  function targetText(marker) {
    const node = findAttr(target, 'data-d1', marker)
    if (!node) return ''
    let text = ''
    walk(node, (item) => {
      if (item.kind === 'text') text += item.text
    })
    return text
  }

  return {
    renderer,
    root,
    target,
    walk,
    classesOf,
    findAttr,
    findClass,
    findLocalAttr,
    targetText,
  }
}

function assertNoTopNav(theme) {
  const moduleNav = theme.match(/\.kgm-module-nav\s*\{[\s\S]*?\}/)?.[0] ?? ''
  const pageNav = theme.match(/\.kgm-page-nav\s*\{[\s\S]*?\}/)?.[0] ?? ''
  assert.match(moduleNav, /flex-direction:\s*column/)
  assert.match(pageNav, /flex-direction:\s*column/)
  assert.doesNotMatch(moduleNav, /flex-wrap:\s*wrap/)
  assert.match(theme, /\.d1-page-navigation\s*\{[\s\S]*?flex-direction:\s*column/)
  const app = fs.readFileSync(path.join(d1Dir, 'App.vue'), 'utf8')
  assert.match(app, /grid-template-columns:\s*240px minmax\(0,\s*1fr\)/)
  assert.match(app, /max-height:\s*calc\(100vh - 24px\)/)
  assert.match(app, /overflow-y:\s*auto/)
  assert.match(app, /@media \(max-width: 640px\)[\s\S]*grid-template-columns:\s*168px minmax\(0,\s*1fr\)/)
}

const harness = new Harness()
const target = '#d1-page-navigation'

{
  const app = fs.readFileSync(path.join(d1Dir, 'App.vue'), 'utf8')
  const settings = fs.readFileSync(path.join(d1Dir, 'views/SettingsView.vue'), 'utf8')
  const collaboration = fs.readFileSync(path.join(d1Dir, 'views/CollaborationPanel.vue'), 'utf8')
  assert.match(app, /id="d1-page-navigation"/)
  assert.match(app, /data-d1="left-rail"/)
  assert.match(app, /navigation-target="PAGE_NAVIGATION_TARGET"/)
  assert.match(app, /@open-todos="\(\) => void openTodosFromWorkbench\(\)"/)
  assert.match(app, /panel="view\.panel \?\? 'home'"/)
  assert.match(settings, /navigationTarget\?: string/)
  assert.match(settings, /<Teleport[\s\S]*:to="navigationTarget \|\| '#d1-page-navigation'"/)
  assert.match(settings, /v-if="activeSection === 'main'"/)
  assert.match(settings, /:navigation-target="navigationTarget"/)
  assert.match(settings, /:navigation-visible="activeSection === 'collaboration'"/)
  assert.match(collaboration, /navigationTarget\?: string/)
  assert.match(collaboration, /navigationVisible\?: boolean/)
  assert.match(collaboration, /<Teleport[\s\S]*navigationVisible/)
  assert.match(settings, /settings-page-body-local/)
  assert.match(settings, /grid-template-columns:\s*220px minmax\(0,\s*1fr\)/)
  assert.match(settings, /grid-template-columns:\s*156px minmax\(0,\s*1fr\)/)
  assert.match(collaboration, /collaboration-page-body-local/)
  assert.match(collaboration, /grid-template-columns:\s*220px minmax\(0,\s*1fr\)/)
  assert.match(collaboration, /grid-template-columns:\s*156px minmax\(0,\s*1fr\)/)
  ok('App/Settings/Collaboration declare the left target, real local columns, and open-todos contract')
}

{
  const theme = fs.readFileSync(path.join(d1Dir, 'theme.css'), 'utf8')
  assertNoTopNav(theme)
  ok('theme keeps both navigation groups vertical and left at every width')
}

{
  const { html, teleports } = await harness.render('views/SettingsView.vue', {
    context: contextFixture(),
    frozen: false,
    navigationTarget: target,
  })
  assert.match(teleports[target] ?? '', /data-d1="settings-page-nav"/)
  assert.match(teleports[target] ?? '', /settings-page-identity/)
  assert.doesNotMatch(html, /data-d1="settings-page-nav"/)
  assert.doesNotMatch(html, /settings-page-body-local/)
  assert.match(html, /data-stub="\.\/AiSettingsPanel.vue"/)
  assert.match(html, /data-stub="\.\/GameConfigPanel.vue"/)
  ok('current Settings page nav teleports to the left target with no empty local column')
}

{
  const local = await harness.render('views/SettingsView.vue', {
    context: contextFixture(),
    frozen: false,
  })
  assert.match(local.html, /settings-page-body-local/)
  assert.match(local.html, /data-d1="settings-page-nav"/)
  assert.doesNotMatch(local.teleports[target] ?? '', /settings-page-nav/)
  ok('standalone Settings keeps its real local left-column fallback')
}

{
  const hidden = await harness.render('views/SettingsView.vue', {
    context: contextFixture(),
    frozen: false,
    section: 'collaboration',
    navigationTarget: target,
  })
  assert.doesNotMatch(hidden.teleports[target] ?? '', /data-d1="settings-page-nav"/)
  assert.doesNotMatch(hidden.html, /data-d1="settings-page-nav"/)
  ok('hidden Settings main section never leaks its page nav through Teleport')
}

{
  const visible = await harness.render('views/CollaborationPanel.vue', {
    navigationTarget: target,
    navigationVisible: true,
  })
  assert.match(visible.teleports[target] ?? '', /data-d1="collaboration-page-nav"/)
  assert.match(visible.teleports[target] ?? '', /collaboration-page-config/)
  assert.doesNotMatch(visible.html, /data-d1="collaboration-page-nav"/)
  assert.doesNotMatch(visible.html, /collaboration-page-body-local/)

  const hidden = await harness.render('views/CollaborationPanel.vue', {
    navigationTarget: target,
    navigationVisible: false,
  })
  assert.doesNotMatch(hidden.teleports[target] ?? '', /data-d1="collaboration-page-nav"/)
  assert.doesNotMatch(hidden.html, /data-d1="collaboration-page-nav"/)

  const standalone = await harness.render('views/CollaborationPanel.vue', {
    navigationVisible: true,
  })
  assert.match(standalone.html, /collaboration-page-body-local/)
  assert.match(standalone.html, /data-d1="collaboration-page-nav"/)
  assert.doesNotMatch(standalone.teleports[target] ?? '', /collaboration-page-nav/)
  ok('Collaboration teleports only its current page nav and keeps a real local left-column fallback')
}

async function settleMini() {
  await vue.nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

{
  const harness = new Harness()
  const mini = await harness.miniRender('views/SettingsView.vue', {
    context: contextFixture(),
    frozen: false,
    navigationTarget: target,
  })
  const aiCount = harness.componentCounts.get('./AiSettingsPanel.vue') ?? 0
  const gameCount = harness.componentCounts.get('./GameConfigPanel.vue') ?? 0
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'))
  assert.equal(mini.findClass(mini.root, 'settings-page-body-local'), null)

  mini.props.section = 'collaboration'
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'), null)
  assert.equal(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'settings-page-nav'),
    null,
  )
  assert.equal(harness.componentCounts.get('./AiSettingsPanel.vue'), aiCount)
  assert.equal(harness.componentCounts.get('./GameConfigPanel.vue'), gameCount)

  mini.props.section = null
  await settleMini()
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'))

  mini.props.navigationTarget = ''
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'), null)
  assert.ok(mini.findClass(mini.root, 'settings-page-body-local'))
  assert.ok(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'settings-page-nav'),
  )
  assert.equal(harness.componentCounts.get('./AiSettingsPanel.vue'), aiCount)
  assert.equal(harness.componentCounts.get('./GameConfigPanel.vue'), gameCount)

  mini.props.navigationTarget = target
  await settleMini()
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'))
  assert.equal(mini.findClass(mini.root, 'settings-page-body-local'), null)
  assert.equal(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'settings-page-nav'),
    null,
  )

  mini.app.unmount()
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'settings-page-nav'), null)
  ok('Settings dynamic target/section switching moves only current nav and keeps child forms mounted')
}

{
  const harness = new Harness()
  const mini = await harness.miniRender('views/CollaborationPanel.vue', {
    navigationTarget: target,
    navigationVisible: true,
  })
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'))
  assert.equal(mini.findClass(mini.root, 'collaboration-page-body-local'), null)

  mini.props.navigationVisible = false
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'), null)
  assert.equal(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'collaboration-page-nav'),
    null,
  )

  mini.props.navigationVisible = true
  await settleMini()
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'))

  mini.props.navigationTarget = ''
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'), null)
  assert.ok(mini.findClass(mini.root, 'collaboration-page-body-local'))
  assert.ok(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'collaboration-page-nav'),
  )

  mini.props.navigationVisible = false
  await settleMini()
  assert.equal(mini.findClass(mini.root, 'collaboration-page-body-local'), null)
  assert.equal(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'collaboration-page-nav'),
    null,
  )

  mini.props.navigationVisible = true
  await settleMini()
  assert.ok(
    mini.findLocalAttr(mini.root, mini.target, 'data-d1', 'collaboration-page-nav'),
  )
  mini.props.navigationTarget = target
  await settleMini()
  assert.ok(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'))
  assert.equal(mini.findClass(mini.root, 'collaboration-page-body-local'), null)

  mini.app.unmount()
  await settleMini()
  assert.equal(mini.findAttr(mini.target, 'data-d1', 'collaboration-page-nav'), null)
  ok('Collaboration dynamic visibility/target switching uses left fallback and cleans up Teleport')
}

console.log(`sidebar-shell: ${passed} checks passed`)
