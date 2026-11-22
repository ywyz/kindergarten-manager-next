/**
 * #19 daily-plan AI placement + 2026-11-15 left-directory layout regression.
 *
 * Executes the real AiTaskPanel SFC script + compiled template in a tiny
 * in-memory DOM with a controlled API. The EditorView structure is checked on
 * the actual SFC source so the read panes, their edit buttons, the three field
 * anchors and the single-panel mount guard cannot drift. This is not a
 * WebView2 run; the real-page Edge probe stays separate. The mounted
 * EditorView behaviour (copy/cancel/confirm/save) lives in
 * daily-layout-ui.test.mjs.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')
const panelFile = path.join(d1Dir, 'views', 'AiTaskPanel.vue')
const editorSource = fs.readFileSync(editorFile, 'utf8')
const panelSource = fs.readFileSync(panelFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function between(source, startToken, endToken, needle, label) {
  const start = source.indexOf(startToken)
  const end = source.indexOf(endToken)
  const at = source.indexOf(needle)
  assert.ok(start >= 0, `${label}: start token missing`)
  assert.ok(end > start, `${label}: end token missing or before start`)
  assert.ok(at > start && at < end, `${label}: ${needle} is outside its section`)
}

// ---------------------------------------------------------------------------
// SFC source/layout contract
// ---------------------------------------------------------------------------

{
  const editor = parse(editorSource, { filename: editorFile })
  assert.equal(editor.errors.length, 0, 'EditorView parses')
  const panel = parse(panelSource, { filename: panelFile })
  assert.equal(panel.errors.length, 0, 'AiTaskPanel parses')

  for (const [label, file, descriptor] of [
    ['EditorView', editorFile, editor.descriptor],
    ['AiTaskPanel', panelFile, panel.descriptor],
  ]) {
    const script = compileScript(descriptor, { id: label })
    const template = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: label,
      compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
    })
    assert.deepEqual(template.errors, [], `${label} template compiles`)
  }

  // 2026-11-22 continuous full preview: the body is one readable document.
  // Every actual column stays mounted and visible; the directory buttons
  // only locate a column.
  const bookStart = editorSource.indexOf('data-d1="daily-book"')
  assert.ok(bookStart > 0, 'the daily book exists')
  const navStart = editorSource.indexOf('class="daily-nav"', bookStart)
  const nav = editorSource.slice(navStart, editorSource.indexOf('</nav>', navStart))
  assert.match(nav, /v-for="section in LAYOUT_SECTIONS"/, 'section buttons come from the real section list')
  assert.match(nav, /:aria-pressed="layoutSection === section\.key \? 'true' : 'false'"/, 'the located button exposes its state')
  assert.match(nav, /:type="layoutSection === section\.key \? 'primary' : 'default'"/, 'the located button uses the primary style')
  assert.match(editorSource, /data-d1="daily-doc-head"/, 'the document head exists')
  assert.match(editorSource, /一日活动计划/, 'the document title names the full plan')
  for (const pane of ['raw-lesson', 'layout-section-morning', 'layout-section-talk', 'layout-section-group', 'layout-section-post', 'layout-section-afternoon', 'layout-section-reflection']) {
    const marker = editorSource.indexOf(`data-d1="${pane}"`)
    assert.ok(marker > navStart, `${pane} section exists after the directory`)
    const paneStart = editorSource.lastIndexOf('<section', marker)
    const paneBlock = editorSource.slice(paneStart, marker + 200)
    assert.doesNotMatch(paneBlock, /v-show="layoutSection/, `${pane} is always visible; no tab switching`)
    assert.match(paneBlock, /:ref="\(el\) => setSectionEl\(/, `${pane} registers its locate anchor`)
  }

  // Raw lesson is readable in the document; its textarea now lives only in
  // the independent edit dialog (read mode by default).
  const rawPane = editorSource.indexOf('data-d1="raw-lesson"')
  const rawRead = editorSource.indexOf('data-d1="read-raw-lesson"')
  const dialogStart = editorSource.indexOf('data-d1="layout-edit-dialog"')
  const rawInput = editorSource.indexOf('data-d1="layout-input-raw"')
  assert.ok(rawRead > rawPane, 'raw text is readable inside its section')
  assert.ok(dialogStart > 0 && rawInput > dialogStart, 'the raw textarea is inside the edit dialog only')
  assert.match(editorSource, /layoutDraft\.raw/, 'the dialog edits its own raw copy')

  // All columns render their real stored fields, including the split baseline
  // and the reflection material.
  for (const marker of [
    'form.group_activity.objectives',
    'form.group_activity.preparation',
    'form.group_activity.key_points',
    'form.group_activity.difficult_points',
    'form.group_activity.process',
    'data-d1="read-split-baseline"',
    'splitBaselineProcess',
    'form.post_group_games',
    'form.afternoon_outdoor.observation_focus',
    'data-d1="read-reflection"',
    'data-d1="read-reflection-materials"',
  ]) {
    assert.ok(editorSource.includes(marker), `the document keeps ${marker}`)
  }
  assert.doesNotMatch(
    editorSource,
    /morningFocusGroupIndex|dailyMorningGroupHasHiddenDetails/,
    'every morning group shows its own stored subfields; no focus-group hiding rule remains',
  )
  for (const field of ['focus_guidance', 'shared_objectives', 'guidance_points']) {
    const morningStart = editorSource.indexOf('data-d1="layout-section-morning"')
    const morningBlock = editorSource.slice(morningStart, editorSource.indexOf('data-d1="layout-section-talk"'))
    assert.equal(
      (morningBlock.match(new RegExp(`group\\.${field}`, 'g')) ?? []).length,
      1,
      `the morning block renders ${field} for every group exactly once`,
    )
  }

  // Operations are not repeated inside the reading document.
  for (const gone of [
    'layout-edit-raw',
    'layout-edit-morning',
    'layout-edit-talk',
    'layout-edit-group',
    'layout-edit-post',
    'layout-edit-afternoon',
    'layout-edit-reflection',
    'section-ai-morning_games',
    'section-ai-morning_talk',
    'section-ai-post_group_games',
    'section-ai-afternoon_outdoor',
    'reflection-generate',
    'reflection-ai-edit',
    'reflection-guidance',
    'ai-slot-daily_lesson_split',
    'ai-slot-daily_process_adapt',
    'ai-slot-daily_other_activities',
    'ai-slot-daily_reflection_generate',
    'reflection-progress-target',
    'split-needs-save',
  ]) {
    assert.ok(!editorSource.includes(`data-d1="${gone}"`), `${gone} is not repeated inside the document`)
  }

  // Main operations: exactly four rail actions in the required order, plus
  // the auxiliary entries (任务 and the real back-to-calendar destination);
  // the shell rail owns the true 返回工作台 and the module navigation owns
  // settings, so the editor must not duplicate either.
  assert.match(editorSource, /data-d1="start-split-from-rail"/)
  assert.match(editorSource, /@click="startSplitFromRail"/)
  assert.match(editorSource, /data-d1="start-split-from-rail"[\s\S]{0,200}拆分教案并修改/)
  assert.match(editorSource, /data-d1="open-modify"[\s\S]{0,200}@click="openModifySection"/)
  assert.match(editorSource, /data-d1="manual-save"/)
  assert.match(editorSource, /data-d1="open-export"/)
  assert.doesNotMatch(editorSource, /data-d1="open-ai-history"/, 'the separate AI history rail entry is consolidated')
  assert.doesNotMatch(editorSource, /data-d1="open-history"/, 'the separate version-history rail entry is consolidated')
  assert.doesNotMatch(editorSource, /data-d1="go-settings"/, 'the duplicate settings entry is removed; module navigation still reaches it')
  const railStart = editorSource.indexOf('data-d1="editor-actions-rail"')
  const railBlock = editorSource.slice(railStart, editorSource.indexOf('</aside>', railStart))
  assert.deepEqual(
    (railBlock.match(/data-d1="([a-z-]+)"/g) ?? [])
      .map((value) => value.slice(9, -1))
      .filter((value) => value !== 'editor-actions-rail'),
    ['start-split-from-rail', 'open-modify', 'manual-save', 'open-export', 'open-tasks', 'back-calendar'],
    'the rail keeps the four main actions in order plus the auxiliary entries',
  )
  assert.match(
    editorSource,
    /data-d1="back-calendar"[\s\S]{0,200}日历与已保存计划/,
    'the right-rail back names its real destination instead of the shell 返回工作台',
  )

  // Every fresh open/date switch starts reading at the preview top.
  assert.match(
    editorSource,
    /const layoutSection = ref<DailyLayoutSectionKey>\('raw'\)/,
    'the initial located column is the top section',
  )
  assert.match(editorSource, /ref="docHeadEl"/, 'the document head registers its locate element')
  assert.match(
    editorSource,
    /function revealDocTopOnce\(\): void \{[\s\S]{0,400}scrollIntoView/,
    'a one-shot reveal scrolls a fresh open to the preview top',
  )
  assert.match(
    editorSource,
    /applyPlan\(found\)\s*\n\s*revealDocTopOnce\(\)/,
    'the open-mode load reveals the top after the plan applies',
  )
  assert.match(
    editorSource,
    /startDraft\(\)\s*\n\s*revealDocTopOnce\(\)/,
    'an empty-date draft reveal starts at the top too',
  )
  assert.match(
    editorSource,
    /ref="actionsRailEl"/,
    'the action rail registers its element for the narrow reveal target',
  )
  assert.match(
    editorSource,
    /narrowActionsViewport\(\)\s*\n\s*\? \(actionsRailEl\.value \?\? docHeadEl\.value\)\s*\n\s*: docHeadEl\.value/,
    'the reveal prefers the action bar when it sits above the document, never scrolling it offscreen',
  )
  // Narrow geometry (760x560 audit): the action group precedes the long
  // reading document, with the wide sticky rail unchanged and one DOM only.
  assert.equal(
    (editorSource.match(/<aside ref="actionsRailEl" class="editor-actions-rail"/g) ?? []).length,
    1,
    'exactly one action rail exists: reordering is CSS-only, no duplicated toolbar DOM',
  )
  const wideLayout = editorSource.slice(
    editorSource.indexOf('.editor-layout {'),
    editorSource.indexOf('@media (max-width: 1100px)'),
  )
  assert.match(wideLayout, /grid-template-columns: minmax\(0, 1fr\) 210px/, 'the wide two-column rail placement is unchanged')
  const railStart1100 = editorSource.indexOf('@media (max-width: 1100px)')
  const narrowBlock = editorSource.slice(railStart1100, editorSource.indexOf('@media (max-width: 760px)'))
  assert.match(narrowBlock, /\.editor-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/, 'the narrow layout collapses to one column')
  assert.match(
    narrowBlock,
    /\.editor-actions-rail\s*\{[\s\S]{0,400}?order:\s*-1/,
    'the narrow single column places the action group BEFORE the reading body via grid order',
  )
  assert.match(
    narrowBlock,
    /\.editor-actions-rail\s*\{[\s\S]{0,500}?position:\s*static/,
    'the narrow action group is in-flow, never overlaying the text',
  )
  assert.match(
    narrowBlock,
    /\.editor-actions-rail\s*\{[\s\S]{0,600}?flex-wrap:\s*wrap/,
    'the narrow buttons wrap instead of clipping horizontally',
  )
  assert.match(narrowBlock, /\.editor-actions-rail \.el-button\s*\{[^}]*width:\s*auto/, 'narrow buttons keep their natural width')

  // Evidence-first display: the fixed activity name follows the stored value.
  assert.match(
    editorSource,
    /const morningExerciseLabel = computed\(\s*\(\) => form\.value\.morning_exercise_label \|\| MORNING_EXERCISE_LABEL,?\s*\)/,
    'the fixed activity name prefers the stored label with the fixed fallback',
  )
  assert.match(editorSource, /晨间 · \{\{ morningExerciseLabel \}\}/)
  assert.match(editorSource, /:data-d1="`read-post-group-\$\{gi\}`"/, 'every post group keeps its own readable block marker')

  // 修改指定内容: one chooser connects hand editing and each column's
  // existing AI workflow.
  assert.match(editorSource, /data-d1="modify-dialog"/)
  assert.match(
    editorSource,
    /:data-d1="`modify-pick-\$\{section\.key\}`"/,
    'every column is choosable through one dynamic pick binding',
  )
  for (const key of ['raw', 'morning', 'talk', 'group', 'post', 'afternoon', 'reflection']) {
    assert.ok(editorSource.includes(`{ key: '${key}'`), `the ${key} column stays in the chooser section list`)
  }
  assert.match(editorSource, /data-d1="modify-edit"[\s\S]{0,120}@click="submitModifyEdit"/)
  assert.match(editorSource, /function submitModifyEdit\(\): void \{[\s\S]{0,200}openLayoutEditor\(section\)/)
  assert.match(editorSource, /const MODIFY_AI: Partial<Record<DailyLayoutSectionKey, ModifyAiMeta>>/)
  for (const key of ['morning_games', 'morning_talk', 'post_group_games', 'afternoon_outdoor']) {
    assert.ok(editorSource.includes(`key: '${key}'`), `${key} keeps its existing targeted AI workflow in the chooser`)
  }
  assert.match(editorSource, /data-d1="modify-ai"[\s\S]{0,200}@click="submitModifyAi"/)
  assert.match(editorSource, /function submitModifyAi\(\): void \{[\s\S]{0,400}openSectionAi\(meta\.key\)/)
  assert.match(editorSource, /openReflectionAi\(\)/)
  assert.match(editorSource, /aiTaskPanelRef\.value\?\.trigger\?\.\('daily_process_adapt'\)/)
  assert.match(editorSource, /data-d1="section-ai-dialog"/)
  assert.match(editorSource, /data-d1="section-ai-submit"/)
  assert.match(editorSource, /data-d1="reflection-ai-dialog"/)
  assert.match(editorSource, /data-d1="reflection-ai-current"/)
  assert.match(editorSource, /data-d1="reflection-ai-submit"/)

  // 任务: the single auxiliary entry leading to AI tasks + version history.
  assert.match(editorSource, /data-d1="tasks-dialog"/)
  assert.match(editorSource, /data-d1="tasks-open-ai"[\s\S]{0,200}@click="openTasksAi"/)
  assert.match(editorSource, /data-d1="tasks-open-history"[\s\S]{0,200}@click="openTasksHistory"/)
  assert.match(editorSource, /function openTasksHistory\(\): void \{[\s\S]{0,120}openHistory\(\)/)
  assert.match(editorSource, /data-d1="tasks-draft-hint"/, 'the no-plan task state is explained, never a dead click')

  // 拆分教案并修改 connects the original-lesson input before the split.
  assert.match(
    editorSource,
    /if \(!hasRaw\.value\) \{[\s\S]{0,300}openLayoutEditor\('raw'\)/,
    'an empty raw lesson opens the original-lesson input dialog first',
  )

  // Exactly one state owner: no duplicated panel, no duplicated trigger set.
  assert.equal((editorSource.match(/<AiTaskPanel\b/g) ?? []).length, 1, 'one AiTaskPanel mount')
  assert.equal((panelSource.match(/ai-trigger-\$\{type\}/g) ?? []).length, 1, 'one inline fallback trigger per type loop')
  const panelMount = editorSource.match(/<AiTaskPanel\b[\s\S]*?\/>/)?.[0] ?? ''
  assert.match(panelMount, /v-if="plan"/)
  assert.match(panelMount, /:plan-id="plan\.id"/)
  assert.doesNotMatch(panelMount, /:split-target=|:process-target=|:other-target=|:reflection-progress-target=/, 'no per-field teleport anchors remain')
  assert.match(panelMount, /:dialog-open="aiTaskDialogOpen"/)
  assert.match(panelMount, /hide-other-row/)
  assert.match(editorSource, /@action-start="onAiActionStart"/)
  assert.doesNotMatch(editorSource, /data-d1="daily-generation-actions"/, 'no second left module/generation list')
  assert.match(panelSource, /emit\('action-start', taskType\)/)
  assert.doesNotMatch(panelSource, /locate-task/, 'removed left-group locate shortcuts stay removed')
  assert.doesNotMatch(editorSource, /@locate-task=/, 'editor has no locate-task wiring')
  assert.match(editorSource, /:to="navigationTarget \|\| 'body'"/, 'directory teleports to the shared target')
  assert.match(editorSource, /:disabled="!navigationTarget"/, 'standalone keeps the local left fallback')
  assert.match(editorSource, /daily-book-teleported/, 'teleported mode drops the inner directory column')
  assert.match(editorSource, /daily-nav-in-rail/, 'rail mode avoids a nested sidebar frame')
  const narrowStart = editorSource.indexOf('@media (max-width: 760px)')
  const narrowStyles = editorSource.slice(narrowStart, editorSource.indexOf('.footer', narrowStart))
  assert.match(narrowStyles, /\.daily-nav\s*\{[^}]*flex-direction:\s*column/, 'narrow daily navigation stays left, not top')
  assert.doesNotMatch(narrowStyles, /\.daily-nav\s*\{[^}]*flex-direction:\s*row/, 'narrow daily navigation never becomes a horizontal row')
  assert.match(narrowStyles, /grid-template-columns:\s*clamp\(150px/, 'narrow book keeps the left rail and content columns')
  assert.match(narrowStyles, /daily-book-teleported[\s\S]{0,120}grid-template-columns:\s*minmax\(0, 1fr\)/, 'teleported narrow layout has one content column')
  assert.match(editorSource, /:content-version="plan\.current_content_version"/)
  assert.match(editorSource, /:has-raw="hasRaw"/)
  assert.match(editorSource, /:has-process="hasProcess"/)
  assert.match(editorSource, /:save-current="saveCurrent"/)
  assert.match(panelMount, /:has-unsaved-changes="formDirtyForAi"/, 'AI task panel gets the live dirty reader')
  assert.match(
    editorSource,
    /<CandidatePreview[\s\S]*?:has-unsaved-changes="formDirtyForAi"/,
    'candidate preview gets the live dirty reader',
  )
  assert.match(
    editorSource,
    /<ExportDialog[\s\S]*?:has-unsaved-changes="dirty"/,
    'the export dialog discloses the unsaved draft before exporting the saved version',
  )

  // The edit dialog is bound to its opening plan/version/section/session and
  // confirm only merges the draft column; cancel never touches the live form.
  assert.match(editorSource, /layoutDraft\.value = cloneDailyLayoutDraft\(/, 'the dialog starts from an independent copy')
  assert.match(editorSource, /layoutOrigin\.value = \{[\s\S]{0,400}version: plan\.value\?\.current_content_version/, 'the dialog pins the opening version')
  assert.match(editorSource, /editEpoch\.value !== origin\.editEpoch/, 'late input invalidates the dialog')
  assert.match(editorSource, /applyDailyLayoutSection\([\s\S]{0,120}form\.value/, 'confirm merges exactly one column into the live draft')
  assert.match(editorSource, /data-d1="layout-edit-cancel"/, 'cancel is explicit and keeps its locator')
  assert.match(editorSource, /data-d1="layout-edit-confirm"/, 'confirm is explicit and keeps its locator')
  assert.match(editorSource, /data-d1="layout-edit-stale"/, 'a page change while open disables a stale confirm')
  assert.match(editorSource, /layoutDraftDirty\.value[\s\S]{0,200}确定填回草稿/, 'a pending dialog joins leave protection')
  assert.match(editorSource, /!layoutEditing\.value/, 'automatic AI writes are blocked while the dialog is open')

  // Existing diagnostics remain the single source for tasks and saving.
  for (const marker of [
    'data-d1="ai-tasks"',
    'data-d1="ai-target-grade"',
    'data-d1="manual-save"',
    'data-d1="resubmit-draft-create"',
  ]) {
    assert.ok(
      (editorSource + panelSource).includes(marker),
      `diagnostic ${marker} remains`,
    )
  }

  ok('editor layout: continuous full document with consolidated rail/chooser entries; edit dialog stays an identity-bound independent copy; one panel remains')
}

// ---------------------------------------------------------------------------
// Real AiTaskPanel SFC in a controlled mini DOM
// ---------------------------------------------------------------------------

const liveHarnesses = []

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor({ fetchImpl } = {}) {
    this.fetchImpl = fetchImpl ?? (() => Promise.reject(new Error('no fetch')))
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.uuidSeq = 0
    this.window = {}
    this.message = () => {}
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
    liveHarnesses.push(this)
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy(
      {},
      {
        get: (_, key) => harness.window[key],
        set: (_, key, value) => {
          harness.window[key] = value
          return true
        },
        has: () => true,
      },
    )
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Promise,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
      fetch: (...args) => harness.fetchImpl(...args),
    }
  }

  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const exportsObject = this._evaluate(source, file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = filename
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename })
    } finally {
      this._currentFile = previous
    }
    return module.exports
  }

  loadSfc(file) {
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: path.basename(file), inlineTemplate: true }).content
    return this._evaluate(compiled, file).default
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function apiError(status, code, message) {
  return jsonResponse(status, { error: { code, message } })
}

function router(routes) {
  const calls = []
  const impl = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const pathOnly = String(url).split('?')[0]
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: String(url), path: pathOnly, body })
    for (const [key, handler] of Object.entries(routes)) {
      const [routeMethod, routePath] = key.split(' ')
      if (routeMethod !== method) continue
      if (routePath.endsWith('*')) {
        if (pathOnly.startsWith(routePath.slice(0, -1))) {
          return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
        }
      } else if (routePath === pathOnly) {
        return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
      }
    }
    return apiError(404, 'NOT_FOUND', `no route for ${method} ${pathOnly}`)
  }
  impl.calls = calls
  return impl
}

function taskFixture(overrides = {}) {
  return {
    id: 'task1',
    plan_id: 'p1',
    task_type: 'daily_lesson_split',
    status: 'pending',
    reason: null,
    processing_certainty: 'not_sent',
    user_stop_requested: false,
    created_at: '2026-11-08T00:00:00Z',
    updated_at: '2026-11-08T00:00:00Z',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: null,
    candidate_id: null,
    allowed_actions: ['cancel'],
    retry_requires_ack: false,
    ...overrides,
  }
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type,
    tag: null,
    text: '',
    props: {},
    children: [],
    parent: null,
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => {
      node.text = text
    },
    setElementText: (node, text) => {
      node.text = text
      node.children = []
    },
    insert: (child, parent, anchor) => {
      child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index >= 0) parent.children.splice(index, 0, child)
      else parent.children.push(child)
    },
    remove: (child) => {
      const parent = child.parent
      if (!parent) return
      const index = parent.children.indexOf(child)
      if (index >= 0) parent.children.splice(index, 1)
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
      const parent = node.parent
      if (!parent) return null
      const index = parent.children.indexOf(node)
      return parent.children[index + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => {
      el.props[key] = next
    },
  }
  return { root, ops }
}

const DomCardStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        slots.header?.(),
        slots.default?.(),
      ])
  },
}

const DomSelectStub = {
  props: { modelValue: String, disabled: Boolean },
  emits: ['update:modelValue'],
  setup(_props, { slots }) {
    return () => vue.h('div', {}, slots.default?.())
  },
}

const DomOptionStub = {
  props: { label: String, value: String },
  setup() {
    return () => null
  },
}

const DomTagStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('span', { 'data-d1': attrs['data-d1'] }, slots.default?.())
  },
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          'data-d1': attrs['data-d1'],
          disabled: !!props.disabled,
          onClick: () => {
            if (!props.disabled) emit('click')
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(_props, { attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] })
  },
}

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}

function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  return (node.children ?? []).map(nodeText).join('') + (node.text ?? '')
}

function byD1(root, value) {
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}

function byD1Button(root, value) {
  return walkElements(root).find(
    (node) => node.tag === 'button' && node.props['data-d1'] === value,
  ) ?? null
}

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what) {
  for (let i = 0; i < 400; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

async function mountPanel({ routes, props = {}, targets = null }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const component = harness.loadSfc(panelFile)
  const { root, ops } = createMiniDom()
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const slotAnchor = (name) => {
    const node = ops.createElement('div')
    node.props['data-d1'] = name
    ops.insert(node, root)
    return node
  }
  const anchors = targets
    ? {
        splitTarget: slotAnchor('slot-split'),
        processTarget: slotAnchor('slot-process'),
        otherTarget: slotAnchor('slot-other'),
      }
    : {}
  const actionStarts = []
  const app = vue.createRenderer(ops).createApp({
    render: () =>
      vue.h(component, {
        planId: 'p1',
        planGrade: 'middle',
        contentVersion: 3,
        hasRaw: true,
        hasProcess: true,
        frozen: false,
        saveCurrent: async () => 'unchanged',
        pollVisibleMs: 5000,
        pollHiddenMs: 5000,
        onOpenCandidate: () => {},
        onOpenGuidance: () => {},
        onDraftActive: () => {},
        onActionStart: (type) => actionStarts.push(type),
        ...anchors,
        ...props,
      }),
  })
  app.component('el-card', DomCardStub)
  app.component('el-button', DomButtonStub)
  app.component('el-select', DomSelectStub)
  app.component('el-option', DomOptionStub)
  app.component('el-tag', DomTagStub)
  app.component('el-alert', DomAlertStub)
  app.mount(appRoot)
  harness.runMounted()
  await settle()
  return {
    harness,
    root,
    appRoot,
    anchors,
    actionStarts,
    calls: fetchImpl.calls,
    app,
  }
}

async function testStandalonePanelKeepsInlineRows() {
  const { harness, appRoot, actionStarts, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
  })
  const card = byD1(appRoot, 'ai-tasks')
  assert.ok(card, 'panel card rendered')
  for (const type of ['daily_lesson_split', 'daily_process_adapt', 'daily_other_activities']) {
    assert.ok(
      byD1(card, `ai-trigger-${type}`),
      `standalone panel keeps the ${type} trigger inline`,
    )
  }
  assert.equal(
    (panelSource.match(/<Teleport/g) ?? []).length,
    2,
    'action-row anchors and observed reflection remain within a single panel',
  )
  assert.match(panelSource, /:disabled="!rowTargets\[type\]"/)
  assert.match(panelSource, /:disabled="task\.id !== observedReflectionTaskId \|\| !reflectionProgressTarget"/)
  const splitTrigger = byD1Button(appRoot, 'ai-trigger-daily_lesson_split')
  assert.equal(nodeText(splitTrigger).trim(), '发起教案拆分', 'the inline split trigger keeps its direct label')
  splitTrigger.props.onClick({})
  await settle()
  assert.deepEqual(actionStarts, ['daily_lesson_split'], 'the standalone entry emits its task context')
  assert.ok(byD1(card, 'ai-target-grade'), 'target grade remains in the single task panel')
  app.unmount()
  harness.unmount()
  ok('panel standalone: all three type rows stay inline when no field targets are present')
}

async function testTargetedRowsAreAdjacentAndSingle() {
  const { harness, root, appRoot, anchors, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () =>
        jsonResponse(200, {
          items: [
            taskFixture({ status: 'succeeded', candidate_id: null, allowed_actions: [] }),
          ],
          next_cursor: null,
        }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
    targets: true,
  })
  const card = byD1(appRoot, 'ai-tasks')
  const mapping = {
    daily_lesson_split: anchors.splitTarget,
    daily_process_adapt: anchors.processTarget,
    daily_other_activities: anchors.otherTarget,
  }
  for (const [type, anchor] of Object.entries(mapping)) {
    assert.ok(byD1(anchor, `ai-trigger-${type}`), `${type} trigger is teleported to its field anchor`)
    assert.equal(byD1(card, `ai-trigger-${type}`), null, `${type} trigger is not duplicated in the panel`)
  }
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1']?.startsWith('ai-trigger-')).length,
    3,
    'exactly one trigger exists per task type across the page',
  )
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1'] === 'ai-tasks').length,
    1,
    'one AI task card owns all three triggers',
  )
  assert.ok(
    byD1(card, 'ai-task'),
    'task history stays in the single panel while the trigger rows move to their fields',
  )
  assert.match(panelSource, /data-d1="ai-target-grade"/)
  app.unmount()
  harness.unmount()
  ok('panel targets: three rows are adjacent to their fields and remain one state owner')
}

async function testSaveAndTaskGatesRemain() {
  const posts = []
  const order = []
  let outcome = 'failed'
  const routes = {
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      order.push('register')
      posts.push(body)
      return jsonResponse(202, taskFixture({ task_type: body.task_type }))
    },
  }
  const { harness, root, appRoot, app } = await mountPanel({
    routes,
    props: {
      saveCurrent: async () => {
        order.push('save')
        return outcome
      },
    },
    targets: true,
  })
  const split = byD1Button(root, 'ai-trigger-daily_lesson_split')
  assert.ok(split, 'split trigger rendered in its anchor')
  split.props.onClick({})
  await settle()
  assert.equal(posts.length, 0, 'a failed save never registers an AI task')
  assert.match(
    harness.window.__d1AiTasks.createError('daily_lesson_split'),
    /正文未保存成功|未发起 AI 任务/,
  )

  outcome = 'saved'
  order.length = 0
  byD1Button(root, 'ai-trigger-daily_lesson_split').props.onClick({})
  await settle()
  assert.deepEqual(order, ['save', 'register'], 'the body saves before the task is registered')
  assert.equal(posts.length, 1)
  assert.equal(posts[0].task_type, 'daily_lesson_split')
  assert.equal(posts[0].expected_content_version, 3)
  assert.equal(posts[0].target_grade, 'middle')
  assert.match(
    String(harness.fetchImpl.calls.find((call) => call.method === 'POST')?.url),
    /\/api\/daily-plans\/p1\/ai-tasks/,
  )
  app.unmount()
  harness.unmount()
  ok('task gate: the existing save-before-register gate, plan id, version and target grade stay intact')
}

async function testMissingInputsDisableTheirOwnTrigger() {
  const { harness, root, appRoot, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
    props: { hasRaw: false, hasProcess: false },
    targets: true,
  })
  assert.equal(byD1Button(root, 'ai-trigger-daily_lesson_split').props.disabled, true)
  assert.equal(byD1Button(root, 'ai-trigger-daily_process_adapt').props.disabled, true)
  assert.equal(byD1Button(root, 'ai-trigger-daily_other_activities').props.disabled, false)
  assert.match(
    harness.window.__d1AiTasks.blockedReason('daily_lesson_split'),
    /原始教案为空/,
  )
  assert.match(
    harness.window.__d1AiTasks.blockedReason('daily_process_adapt'),
    /集体活动过程为空/,
  )
  app.unmount()
  harness.unmount()
  ok('task gate: missing raw/process input still disables only the dependent trigger')
}

await testStandalonePanelKeepsInlineRows()
await testTargetedRowsAreAdjacentAndSingle()
await testSaveAndTaskGatesRemain()
await testMissingInputsDisableTheirOwnTrigger()

console.log(`daily-layout: ${passed} checks passed`)
