/**
 * #41/#42 listening observation-month and work-date pure rules.
 * No database or component mount.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const clientStub = {
  ApiError: class ApiError extends Error {},
  apiGet: () => {
    throw new Error('unexpected apiGet')
  },
  apiPost: () => {
    throw new Error('unexpected apiPost')
  },
  apiPatch: () => {
    throw new Error('unexpected apiPatch')
  },
  apiDelete: () => {
    throw new Error('unexpected apiDelete')
  },
  apiUpload: () => {
    throw new Error('unexpected apiUpload')
  },
  apiGetBlob: () => {
    throw new Error('unexpected apiGetBlob')
  },
  pathSegment: (value) => encodeURIComponent(String(value)),
}

function loadCore() {
  const file = path.join(d1Dir, 'listening.ts')
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === './client') return clientStub
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Number,
    Object,
    Array,
    String,
    Boolean,
    Promise,
    Map,
    Set,
    URLSearchParams,
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000000' },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

const core = loadCore()
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function group(id, position, workDate) {
  return {
    group_id: id,
    position,
    work_date: workDate,
    listening_text: null,
    asset_id: null,
  }
}

// Strict canonical parsing; old text returns null.
{
  const parsed = core.parseListeningMonth('2026-11')
  assert.equal(parsed?.year, 2026)
  assert.equal(parsed?.month, 11)
  assert.equal(core.parseListeningMonth('11月1—3日'), null)
  assert.equal(core.parseListeningMonth('2026-13'), null)
  assert.equal(core.parseListeningMonth('٢٠٢٧-٠٢'), null)
  assert.equal(core.parseListeningMonth('２０２７-０２'), null)
  assert.equal(core.parseListeningDate('2027-01-31')?.iso, '2027-01-31')
  assert.equal(core.parseListeningDate('2026-02-30'), null)
  assert.equal(core.parseListeningDate('11月1—3日'), null)
  assert.equal(core.parseListeningDate('٢٠٢٧-٠٢-٠٧'), null)
  assert.equal(core.parseListeningDate('２０２７-０２-０７'), null)
  ok('only strict canonical month/date values are interpreted')
}

// Term months and partial-term intersection, including New Year.
{
  const term = core.termMonthRange('2026-09-15', '2027-02-10')
  assert.equal(term?.min, '2026-09')
  assert.equal(term?.max, '2027-02')
  const september = core.workDateRange('2026-09-15', '2027-02-10', '2026-09')
  assert.equal(september?.min, '2026-09-15')
  assert.equal(september?.max, '2026-09-30')
  const february = core.workDateRange('2026-09-15', '2027-02-10', '2027-02')
  assert.equal(february?.min, '2027-02-01')
  assert.equal(february?.max, '2027-02-10')
  assert.equal(core.workDateRange('2026-09-15', '2027-02-10', '2026-08'), null)
  ok('term month limits and cross-year day intersections are exact')
}

// Legacy and out-of-range work dates are per-group issues.
{
  const groups = [
    group('g0', 0, '11月1—3日'),
    group('g1', 1, '2026-12-20'),
    group('g2', 2, '2027-01-15'),
  ]
  const issues = core.listeningDateIssues(
    '2027-01',
    groups,
    '2026-09-01',
    '2027-01-31',
  )
  assert.equal(issues.map((issue) => issue.groupId).join(','), 'g0,g1')
  assert.match(issues[0].reason, /原作品日期/)
  assert.match(issues[1].reason, /交集/)
  assert.equal(
    core.listeningDateIssues(
      '11月1—3日',
      groups,
      '2026-09-01',
      '2027-01-31',
    ).length,
    0,
  )
  ok('legacy and out-of-range dates are located per group without rewriting')
}

// Date dirtiness distinguishes date edits from unrelated text.
{
  const base = {
    domain: 'health',
    observation_date: '2026-12',
    groups: [group('g0', 0, '2026-12-20')],
  }
  const current = {
    ...base,
    groups: [group('g0', 0, '2026-12-20')],
  }
  assert.equal(core.dateFieldsChanged(base, current), false)
  current.groups[0].work_date = '2026-12-21'
  assert.equal(core.dateFieldsChanged(base, current), true)
  current.groups[0].work_date = '2026-12-20'
  current.observation_date = '2027-01'
  assert.equal(core.dateFieldsChanged(base, current), true)
  ok('date-field changes are isolated from unrelated text dirtiness')
}

console.log(`listening-dates: ${passed} checks passed`)
