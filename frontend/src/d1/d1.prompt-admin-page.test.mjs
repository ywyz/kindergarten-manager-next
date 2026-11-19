/**
 * Pure contract checks for the fourth-stage prompt-release admin page.
 * No browser, network, database, credentials, signing key or deployment.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const pagePath = path.resolve(
  here,
  '../../../backend/app/collaboration/admin_page.html',
)
const source = fs.readFileSync(pagePath, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

assert.match(source, /<details id="prompt-release-panel"/)
assert.match(source, /<summary>提示词发布<\/summary>/)
assert.match(source, /!state\.promptLoaded/)
assert.match(source, /promptPanel\.addEventListener\("toggle"/)
ok('prompt release area is a collapsed, lazy-loaded disclosure')

for (const route of [
  '/api/collaboration/admin/prompt-releases',
  '/api/collaboration/admin/prompt-releases/drafts',
  '/api/collaboration/admin/prompt-releases/preview',
  '/api/collaboration/admin/prompt-releases/stable',
  '/api/collaboration/admin/prompt-releases/rollback',
]) {
  assert.ok(source.includes(route), route)
}
ok('all five release contract routes are wired')

for (const field of [
  'draft_id',
  'base_stable_sequence',
  'changes',
  'notes',
  'release_sequence',
  'channel',
  'rollback_of',
  'preview_sequence',
  'target_sequence',
  'expected_stable_sequence',
  'latest',
]) {
  assert.ok(source.includes(field), field)
}
ok('draft, preview, stable, rollback and latest fields are represented')

assert.match(source, /function promptBaseLabel/)
assert.match(source, /尚无正式版（内置默认）/)
assert.match(source, /promptBaseLabel\(draft\.base_stable_sequence\)/)
assert.match(
  source,
  /promptBaseLabel\(draft \? draft\.base_stable_sequence : null\)/,
)
assert.doesNotMatch(source, /正式基准 v" \+ String/)
assert.match(source, /function effectivePromptText/)
assert.match(source, /promptPreviewContent\.textContent/)
assert.match(source, /comparison|服务端当前|基准/)
assert.match(source, /正式渠道/)
assert.match(source, /预览渠道/)
assert.match(source, /确认回滚/)
ok('exact preview content, channels, versions and rollback confirmation are visible')

assert.match(source, /Object\.keys\(task\.fields\)/)
assert.match(source, /changes:|notes:/)
assert.match(source, /promptStage\.addEventListener/)
assert.match(source, /promptSaveDraft\.addEventListener/)
ok('allowed task/field selection and draft save are wired')

assert.match(source, /task_label/)
assert.match(source, /field_labels/)
assert.match(source, /function promptTaskLabel/)
assert.match(source, /function promptFieldLabel/)
assert.match(source, /function promptTaskFieldText/)
// Every option text shows the Chinese label together with the real
// identifier; server-provided labels stay authoritative, an older deployed
// backend without the label fields gets the page's presentation-only
// fallback copies, and an unknown future key renders as itself.
assert.match(source, /function optionText\(label, key\)/)
assert.match(source, /TASK_LABEL_FALLBACK/)
assert.match(source, /FIELD_LABEL_FALLBACK/)
assert.match(source, /optionText\(\s*promptTaskLabel\(task\.task_type\), task\.task_type\s*\)/)
assert.match(source, /optionText\(\s*promptFieldLabel\(taskType, fieldName\), fieldName\s*\)/)
assert.match(source, /option\.title = task\.task_type;/)
assert.match(source, /option\.title = fieldName;/)
assert.doesNotMatch(source, /"其他任务"/)
assert.doesNotMatch(source, /"其他字段"/)
ok('task and field choices show Chinese labels with the real identifier')

assert.match(source, /<h2>已有园所名称<\/h2>/)
assert.match(source, /id="school-list"/)
assert.match(source, /id="school-error"/)
assert.match(source, /保存园所名称/)
assert.match(source, /稳定园所 ID/)
assert.match(source, /expected_name: expected, new_name: next/)
assert.match(source, /SCHOOL_NAME_CONFLICT|园所名称已在其他窗口修改/)
ok('existing school display name can be renamed with an old-name baseline')

assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/)
assert.match(source, /textContent/)
ok('dynamic DOM uses textContent only')

assert.ok(!source.includes('\r'), 'admin page keeps LF line endings')
assert.ok(!source.includes(');          school.name'))
assert.ok(!source.startsWith('\ufeff'), 'admin page has no BOM')

const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? ''
assert.ok(script.length > 0, 'admin script exists')
assert.doesNotThrow(() => {
  // Syntax-only compile; the script is not executed and no DOM is touched.
  new Function(script)
}, 'admin script compiles')
ok('admin script compiles')

const collaborationSource = fs.readFileSync(
  path.resolve(here, 'views/CollaborationPanel.vue'),
  'utf8',
)
const settingsSource = fs.readFileSync(
  path.resolve(here, 'views/SettingsView.vue'),
  'utf8',
)
const aiSettingsSource = fs.readFileSync(
  path.resolve(here, 'views/AiSettingsPanel.vue'),
  'utf8',
)
assert.match(collaborationSource, /collaboration-bound-school/)
assert.match(collaborationSource, /collaboration-no-class/)
assert.match(collaborationSource, /collaboration-no-candidates/)
assert.match(collaborationSource, /collaboration-data-boundary/)
assert.match(collaborationSource, /directoryLoaded/)
const redeemBlock = collaborationSource.slice(
  collaborationSource.indexOf('async function redeemWithCode'),
  collaborationSource.indexOf('async function disconnect'),
)
assert.doesNotMatch(redeemBlock, /selectClass\(/)
assert.match(settingsSource, /settings-data-boundary/)
assert.match(settingsSource, /:open="groupOpen\('games'\)"/)
assert.match(aiSettingsSource, /providerOpen = ref\(true\)/)
assert.match(aiSettingsSource, /PROMPT_FIELD_LABELS/)
assert.match(aiSettingsSource, /observation_goal: '观察目标'/)
ok('collaboration and settings boundary/default-open contracts are present')

// ---------------------------------------------------------------------------
// Equivalent-DOM behavior checks.  The REAL admin page script executes
// against a faithful DOM subset (ids, elements, events, select semantics);
// only the network is replaced with scripted responses.  The assertions
// read the actual rendered <option> elements of the task/field dropdowns,
// the staged-change rows, the release/rollback rendering, and the
// provisioning create retry that keeps one entity id while the outcome of
// a request is unknown.  No browser, no backend, no database.

class ShimNode {
  constructor(tag, id) {
    this.tagName = String(tag).toLowerCase()
    this.id = id || ''
    this._text = ''
    this._children = []
    this._listeners = Object.create(null)
    this._attrs = Object.create(null)
    this._classes = new Set()
    this.parentNode = null
    this.value = ''
    this.disabled = false
    this.className = ''
    this.htmlFor = ''
    this.title = ''
    this.placeholder = ''
    this.type = ''
    this.open = false
    this.maxLength = -1
    const sync = () => {
      this.className = [...this._classes].join(' ')
    }
    this.classList = {
      add: (...names) => {
        for (const name of names) this._classes.add(name)
        sync()
      },
      remove: (...names) => {
        for (const name of names) this._classes.delete(name)
        sync()
      },
      contains: (name) => this._classes.has(name),
      toggle: (name, force) => {
        const target = force === undefined
          ? !this._classes.has(name)
          : Boolean(force)
        if (target) this._classes.add(name)
        else this._classes.delete(name)
        sync()
        return target
      },
    }
  }

  get children() {
    return this._children.slice()
  }

  set textContent(value) {
    this._text = String(value)
    this._children = []
  }

  get textContent() {
    return this._text + this._children.map((child) => child.textContent).join('')
  }

  appendChild(child) {
    child.parentNode = this
    this._children.push(child)
    // A real <select> keeps a matching option selected; when the option
    // list no longer contains the current value, the first option becomes
    // the selection again.
    if (this.tagName === 'select' && child.tagName === 'option') {
      const matches = this.value !== '' && this._children.some(
        (option) => option.tagName === 'option' && option.value === this.value,
      )
      if (!matches && this._children[0].value !== '') {
        this.value = this._children[0].value
      }
    }
    return child
  }

  addEventListener(type, handler) {
    if (!this._listeners[type]) this._listeners[type] = []
    this._listeners[type].push(handler)
  }

  fire(type) {
    for (const handler of this._listeners[type] || []) {
      handler({ type, preventDefault() {} })
    }
  }

  setAttribute(name, value) {
    this._attrs[name] = String(value)
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this._attrs, name)
      ? this._attrs[name]
      : null
  }
}

function parseAttrs(attrText) {
  const attrs = {}
  const pattern = /([a-zA-Z][a-zA-Z0-9-]*)\s*=\s*"([^"]*)"/g
  let match
  while ((match = pattern.exec(attrText))) {
    attrs[match[1].toLowerCase()] = match[2]
  }
  return attrs
}

function buildDocumentFromPage(pageHtml) {
  const byId = new Map()
  const root = new ShimNode('body', '')
  const stack = [root]
  const voidTags = new Set([
    'input', 'br', 'hr', 'img', 'meta', 'link', 'source', 'col',
    'area', 'base', 'embed', 'track', 'wbr',
  ])
  const bodyMatch = pageHtml.match(/<body>([\s\S]*?)<\/body>/)
  // The inline script executes separately; never scan its text as markup.
  const bodyHtml = bodyMatch
    ? bodyMatch[1].replace(/<script>[\s\S]*?<\/script>/, '')
    : ''
  const tagPattern = /<\/?([a-zA-Z][a-zA-Z0-9]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g
  let lastIndex = 0
  let match
  while ((match = tagPattern.exec(bodyHtml))) {
    const text = bodyHtml.slice(lastIndex, match.index)
    if (text.trim()) {
      stack[stack.length - 1]._text += text.replace(/\s+/g, ' ')
    }
    lastIndex = match.index + match[0].length
    const tag = match[1].toLowerCase()
    if (match[0].startsWith('</')) {
      while (stack.length > 1 && stack[stack.length - 1].tagName !== tag) {
        stack.pop()
      }
      if (stack.length > 1) stack.pop()
      continue
    }
    const attrs = parseAttrs(match[2] || '')
    const node = new ShimNode(tag, attrs.id || '')
    if (attrs.class) {
      for (const cls of attrs.class.split(/\s+/)) {
        if (cls) node._classes.add(cls)
      }
      node.className = attrs.class
    }
    if (Object.prototype.hasOwnProperty.call(attrs, 'value')) {
      node.value = attrs.value
    }
    if (attrs.for) node.htmlFor = attrs.for
    if (attrs.maxlength) node.maxLength = Number(attrs.maxlength)
    if (attrs.type) node.type = attrs.type
    if (attrs.placeholder) node.placeholder = attrs.placeholder
    if (attrs.id) byId.set(attrs.id, node)
    stack[stack.length - 1].appendChild(node)
    if (!voidTags.has(tag)) stack.push(node)
  }
  return {
    byId,
    document: {
      cookie: '',
      createElement: (tag) => new ShimNode(tag, ''),
      getElementById: (id) => {
        if (!byId.has(id)) byId.set(id, new ShimNode('div', id))
        return byId.get(id)
      },
    },
  }
}

function findButton(root, text) {
  const walk = (node) => {
    for (const child of node.children) {
      if (child.tagName === 'button' && child.textContent === text) {
        return child
      }
      const found = walk(child)
      if (found) return found
    }
    return null
  }
  return walk(root)
}

const SID = '11111111-111-4111-8111-111111111111'
const fetchCalls = []
const mockState = { failTeacherPost: false, teachers: [] }
let uuidCounter = 0

function promptWorkspace() {
  return {
    editable: [
      {
        task_type: 'daily_lesson_split',
        task_label: '日计划·教案拆分',
        fields: { theme: '内置主题指导', objectives: '内置目标指导' },
        field_labels: { theme: '活动主题', objectives: '目标' },
      },
      {
        // An older deployed backend without the label fields.
        task_type: 'game_observation_generate',
        fields: { observation_goal: '内置观察目标' },
      },
      {
        // Future identifiers: the server falls back to the raw keys.
        task_type: 'future_task_x',
        task_label: 'future_task_x',
        fields: { future_field_y: '内置未知指导' },
        field_labels: { future_field_y: 'future_field_y' },
      },
    ],
    drafts: [
      {
        draft_id: '22222222-2222-4222-8222-222222222222',
        notes: '合成草稿',
        base_stable_sequence: null,
        changes: {
          future_task_x: { future_field_y: '草稿中的未知字段文字' },
        },
      },
    ],
    releases: [
      {
        release_sequence: 2,
        channel: 'stable',
        draft_id: null,
        notes: null,
        rollback_of: null,
      },
      {
        release_sequence: 1,
        channel: 'stable',
        draft_id: null,
        notes: null,
        rollback_of: null,
      },
    ],
    latest: { preview: null, stable: 2 },
  }
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status < 400,
    status,
    text: async () => JSON.stringify(payload),
  }
}

async function fakeFetch(path, options) {
  const opts = options || {}
  const method = opts.method || 'GET'
  fetchCalls.push({
    path,
    method,
    body: opts.body === undefined ? null : JSON.parse(opts.body),
  })
  if (path === '/api/collaboration/admin/session') {
    return jsonResponse({ admin_id: SID, username: 'admin-test' })
  }
  if (path === '/api/collaboration/admin/schools' && method === 'GET') {
    return jsonResponse([{ school_id: SID, name: '合成园' }])
  }
  if (path === `/api/collaboration/admin/schools/${SID}/teachers`) {
    if (method === 'POST') {
      if (mockState.failTeacherPost) throw new Error('synthetic network drop')
      const last = fetchCalls[fetchCalls.length - 1]
      return jsonResponse({
        teacher_id: last.body.teacher_id,
        display_name: last.body.name,
        active: true,
        created: true,
      })
    }
    return jsonResponse(mockState.teachers)
  }
  if (path === `/api/collaboration/admin/schools/${SID}/terms` && method === 'GET') {
    return jsonResponse([])
  }
  if (path === `/api/collaboration/admin/schools/${SID}/classes` && method === 'GET') {
    return jsonResponse([])
  }
  if (path === '/api/collaboration/admin/prompt-releases') {
    return jsonResponse(promptWorkspace())
  }
  throw new Error(`unexpected fetch ${method} ${path}`)
}

const settle = async (rounds = 6) => {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const pageScript = source.match(/<script>([\s\S]*?)<\/script>/)[1]
const { byId, document: shimDocument } = buildDocumentFromPage(source)
const fakeWindow = {
  confirm: () => true,
  crypto: {
    randomUUID: () => {
      uuidCounter += 1
      return `synthetic-uuid-${uuidCounter}`
    },
    getRandomValues: (array) => {
      for (let index = 0; index < array.length; index += 1) {
        array[index] = index
      }
      return array
    },
  },
}
new Function('document', 'window', 'fetch', 'crypto', pageScript)(
  shimDocument,
  fakeWindow,
  fakeFetch,
  fakeWindow.crypto,
)
await settle()

assert.equal(byId.get('login-panel').classList.contains('hidden'), true)
assert.equal(byId.get('admin-area').classList.contains('hidden'), false)
assert.equal(
  byId.get('issue-hint').textContent.includes('暂无教师'),
  true,
  'empty teacher list explains the issuing path',
)
ok('scripted session opens the admin area with empty-list guidance')

const panel = byId.get('prompt-release-panel')
panel.open = true
panel.fire('toggle')
await settle()

const taskSelect = byId.get('prompt-task')
const fieldSelect = byId.get('prompt-field')
const taskOptions = taskSelect.children
assert.equal(taskOptions.length, 3)
assert.equal(taskOptions[0].tagName, 'option')
assert.equal(taskOptions[0].value, 'daily_lesson_split')
assert.equal(
  taskOptions[0].textContent,
  '日计划·教案拆分（daily_lesson_split）',
)
assert.equal(
  taskOptions[1].textContent,
  '游戏观察·记录生成（game_observation_generate）',
)
assert.equal(taskOptions[2].textContent, 'future_task_x')
assert.equal(taskSelect.value, 'daily_lesson_split')
assert.deepEqual(
  fieldSelect.children.map((option) => option.textContent),
  ['活动主题（theme）', '目标（objectives）'],
)
ok('dropdowns render Chinese labels with the real identifier for the current structure')

taskSelect.value = 'game_observation_generate'
taskSelect.fire('change')
await settle(2)
assert.equal(
  fieldSelect.children.map((option) => option.textContent).join('|'),
  '观察目标（observation_goal）',
)
ok('an older backend without label fields still shows the Chinese fallback')

taskSelect.value = 'future_task_x'
taskSelect.fire('change')
await settle(2)
assert.equal(fieldSelect.children.length, 1)
assert.equal(fieldSelect.children[0].textContent, 'future_field_y')
assert.equal(byId.get('prompt-text').value, '内置未知指导')
ok('unknown future keys stay recognizable as the raw identifier')

byId.get('prompt-text').value = '页面暂存的新指导'
byId.get('prompt-stage').fire('click')
const staged = byId.get('prompt-staged')
assert.equal(
  staged.textContent.includes('future_task_x / future_field_y'),
  true,
)
assert.equal(staged.textContent.includes('页面暂存的新指导'), true)
assert.equal(
  byId.get('prompt-draft-hint').textContent.includes('1 项字段修改'),
  true,
)
const editButton = findButton(staged, '编辑此修改')
assert.ok(editButton, 'staged row exposes an edit button')
editButton.fire('click')
assert.equal(taskSelect.value, 'future_task_x')
assert.equal(fieldSelect.value, 'future_field_y')
assert.equal(byId.get('prompt-text').value, '页面暂存的新指导')
ok('staging and edit echo work through real DOM events')

const drafts = byId.get('prompt-drafts')
assert.equal(drafts.textContent.includes('1 项修改'), true)
assert.equal(drafts.textContent.includes('尚无正式版（内置默认）'), true)
const releases = byId.get('prompt-releases')
assert.equal(releases.textContent.includes('正式渠道 · 发布序号 v2'), true)
assert.equal(releases.textContent.includes('正式渠道 · 发布序号 v1'), true)
const rollbackButton = findButton(releases, '选择回滚到此正式版')
assert.ok(rollbackButton, 'older stable release offers a rollback entry')
rollbackButton.fire('click')
const rollbackBox = byId.get('prompt-rollback')
assert.equal(rollbackBox.classList.contains('hidden'), false)
assert.equal(byId.get('prompt-rollback-meta').textContent.includes('v1'), true)
assert.equal(byId.get('prompt-rollback-meta').textContent.includes('v2'), true)
assert.ok(
  findButton(rollbackBox, '确认回滚到该正式版'),
  'rollback confirmation stays reachable',
)
ok('draft, release and rollback rendering survive unknown future keys')

// Provisioning: one entity id per create request; the id is kept while the
// outcome is unknown (retried verbatim) and a new input gets a new id.
const teacherName = byId.get('new-teacher-name')
const teacherButton = byId.get('create-teacher-button')
teacherName.value = '王老师'
teacherName.fire('input')
mockState.failTeacherPost = true
teacherButton.fire('click')
await settle(3)
const teacherPosts = () =>
  fetchCalls.filter(
    (call) =>
      call.method === 'POST' &&
      call.path === `/api/collaboration/admin/schools/${SID}/teachers`,
  )
const firstPost = teacherPosts()[0]
assert.ok(firstPost, 'first create POST was sent')
assert.equal(firstPost.body.name, '王老师')
assert.ok(firstPost.body.teacher_id, 'create POST carries the request id')
assert.notEqual(byId.get('new-teacher-error').textContent.length, 0)

teacherButton.fire('click')
await settle(3)
const retryPost = teacherPosts()[1]
assert.ok(retryPost, 'retry create POST was sent')
assert.equal(retryPost.body.teacher_id, firstPost.body.teacher_id)
assert.equal(retryPost.body.name, '王老师')
ok('an unknown create outcome replays the same entity id')

mockState.failTeacherPost = false
teacherButton.fire('click')
await settle(10)
assert.equal(
  byId.get('new-teacher-notice').textContent.includes('已新增教师：王老师'),
  true,
)
assert.equal(teacherName.value, '', 'confirmed success clears the input')

teacherName.value = '李老师'
teacherName.fire('input')
teacherButton.fire('click')
await settle(8)
const nextPost = teacherPosts().at(-1)
assert.ok(nextPost, 'a new create POST was sent')
assert.equal(nextPost.body.name, '李老师')
assert.notEqual(nextPost.body.teacher_id, firstPost.body.teacher_id)
ok('a new input after a confirmed success gets a fresh entity id')

// Same-name teachers stay visually distinguishable in the issue dropdown:
// each option carries its own stable-id tail next to the display name.
mockState.teachers = [
  {
    teacher_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    display_name: '王老师',
    active: true,
  },
  {
    teacher_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    display_name: '王老师',
    active: true,
  },
  {
    teacher_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    display_name: '王老师',
    active: false,
  },
]
byId.get('school').fire('change')
await settle(6)
const issueOptions = byId.get('teacher').children
assert.equal(issueOptions.length, 3)
assert.equal(issueOptions[0].tagName, 'option')
assert.equal(
  issueOptions[0].textContent,
  '王老师（ID 尾号 aaaa）',
)
assert.equal(
  issueOptions[1].textContent,
  '王老师（ID 尾号 bbbb）',
)
assert.equal(
  issueOptions[2].textContent,
  '王老师（ID 尾号 cccc）（已停用，不可发码）',
)
assert.equal(issueOptions[0].value, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
assert.equal(issueOptions[2].disabled, true)
assert.notEqual(issueOptions[0].textContent, issueOptions[1].textContent)
assert.equal(byId.get('issue-hint').classList.contains('hidden'), true)
ok('same-name teacher options are visually distinguishable by id tail')

console.log(`\n${passed} checks passed`)
