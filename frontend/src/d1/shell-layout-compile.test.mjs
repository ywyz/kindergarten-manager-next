/**
 * Real @vue/compiler-sfc parse + template compile gate for every D-touched
 * SFC. This catches broken markup that vue-tsc may not report.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const files = [
  'App.vue',
  'views/WorkbenchView.vue',
  'views/WorkbenchTodoPanel.vue',
  'views/SettingsView.vue',
  'views/SetupView.vue',
  'views/CollaborationPanel.vue',
  'views/BackupRestorePanel.vue',
  'views/UpdatePanel.vue',
  'views/AiSettingsPanel.vue',
  'views/GameConfigPanel.vue',
]

const compiled = new Map()
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

for (const relative of files) {
  const file = path.join(d1Dir, relative)
  const source = fs.readFileSync(file, 'utf8')
  const parsed = parse(source, { filename: file })
  assert.deepEqual(parsed.errors, [], `${relative}: parse errors ${JSON.stringify(parsed.errors)}`)
  assert.ok(parsed.descriptor.template, `${relative}: template block`)
  const script = compileScript(parsed.descriptor, { id: relative })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: file,
    id: relative,
    compilerOptions: {
      mode: 'function',
      bindingMetadata: script.bindings,
      isTS: true,
      expressionPlugins: ['typescript'],
    },
  })
  assert.deepEqual(template.errors, [], `${relative}: template errors ${JSON.stringify(template.errors)}`)
  compiled.set(relative, template.code)
}

const required = {
  'App.vue': [
    'module-nav-workbench', 'module-nav-daily', 'module-nav-settings',
    'ref: "workbenchRef"',
  ],
  'views/WorkbenchView.vue': ['workbench-sidebar', 'workbench-nav-daily', 'workbench-nav-todos', 'plan-list'],
  'views/WorkbenchTodoPanel.vue': ['todo-table', 'todo-editor', 'todo-editor-apply', 'todo-editor-cancel'],
  'views/SettingsView.vue': [
    'settings-override-summary', 'edit-override', 'preview-override',
    'settings-editor-profile', 'settings-editor-apply', 'settings-editor-cancel',
    'settings-backup-table', 'settings-update-table',
  ],
  'views/SetupView.vue': ['setup-summary', 'setup-edit-identity', 'setup-edit-term', 'setup-editor-apply'],
  'views/CollaborationPanel.vue': ['collaboration-directory', 'collaboration-nav-promotion', 'collaboration-nav-game-config'],
  'views/AiSettingsPanel.vue': ['ai-config-editor', 'ai-config-editor-apply', 'ai-prompt-editor', 'ai-prompt-editor-apply'],
  'views/GameConfigPanel.vue': ['game-config-summary', 'game-config-editor', 'game-config-editor-apply', 'game-import-editor'],
  'views/BackupRestorePanel.vue': ['backup-status-table', 'backup-operations-table'],
  'views/UpdatePanel.vue': ['update-status-table', 'update-status-operations'],
}
for (const [file, markers] of Object.entries(required)) {
  const code = compiled.get(file)
  for (const marker of markers) {
    assert.ok(code.includes(marker), `${file}: template contains ${marker}`)
  }
}
const todo = fs.readFileSync(path.join(d1Dir, 'views/WorkbenchTodoPanel.vue'), 'utf8')
assert.equal((todo.match(/<template>/g) ?? []).length, 1)
assert.equal((todo.match(/data-d1="todo-title"/g) ?? []).length, 1)
assert.equal((todo.match(/data-d1="todo-save"/g) ?? []).length, 1)
assert.equal((todo.match(/data-d1="todo-editor"/g) ?? []).length, 1)
ok('all D SFCs parse and compile; todo template has no duplicate controls')
console.log(`shell-layout-compile: ${passed} checks passed`)