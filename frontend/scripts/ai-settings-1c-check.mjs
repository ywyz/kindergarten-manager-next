// Directed verification for AI settings slice 1C.
//
// Run with the already-installed Node (no new dependencies, no test
// framework):  node scripts/ai-settings-1c-check.mjs
//
// This exercises the REAL shipped helpers (type stripping is native in the
// repo's Node 26 runtime), the ones the components actually call:
//  - secret omission keeps no field (no null/''/mask ever serialized)
//  - a typed new secret is sent RAW (no trim) once, only once
//  - DELETE body contains exactly expected_version
//  - dirty computation against partial baselines
//  - stale-response epoch invalidation
//  - fixed error-code notices (fixed generic 422, no raw leaks)
// It does NOT perform browser acceptance and does not start any server.

import {
  aiErrorNotice,
  buildConfigDeletePayload,
  buildConfigPatchPayload,
  changedGuidanceFields,
  createEpochGuard,
  readyStatusText,
  taskDisplayName,
  isKnownTaskType,
} from '../src/components/ai/ai-settings-shared.ts'

let failures = 0
let checks = 0

function check(label, condition, detail) {
  checks += 1
  if (!condition) {
    failures += 1
    console.error(`FAIL: ${label}${detail ? ` — ${detail}` : ''}`)
  }
}

// 1. Secret omission: an empty input must serialize WITHOUT any secret key,
//    and must not contain null, '' or the display mask anywhere.
{
  const p = buildConfigPatchPayload(3, 'https://api.example.com', 'model-a', '')
  const json = JSON.stringify(p)
  check('omit: field absent from object', !Object.prototype.hasOwnProperty.call(p, 'secret'))
  check('omit: no "secret" substring in JSON', !json.includes('"secret"'), json)
  check('omit: no null/empty/mask residue', !json.includes('null') && !json.includes('********'), json)
  check('omit: full metadata present',
    p.expected_version === 3 &&
    p.protocol_id === 'chat_completions_v1' &&
    p.base_url === 'https://api.example.com' &&
    p.model === 'model-a')
}

// 2. A typed new secret rides ONCE, raw (typo-style spaces preserved).
{
  const raw = '  sk-ab12"c34  '
  const p = buildConfigPatchPayload(3, 'https://api.example.com', 'm', raw)
  check('raw secret kept verbatim', p.secret === raw, JSON.stringify(p.secret))
  const json = JSON.stringify(p)
  check('raw secret serialized exactly once', (json.match(/sk-ab12/g) || []).length === 1)
  check('no mask roundtrip', !json.includes('********'))
}

// 3. DELETE payload: exactly one key, exactly expected_version.
{
  const d = buildConfigDeletePayload(7)
  check('delete: single key', Object.keys(d).length === 1 && d.expected_version === 7)
  check('delete: JSON is exact', JSON.stringify(d) === '{"expected_version":7}',
    JSON.stringify(d))
  const d0 = buildConfigDeletePayload(0)
  check('delete: version 0 stays 0 (no-head idempotent)', JSON.stringify(d0) === '{"expected_version":0}')
}

// 4. Dirty computation against partial baselines and '' semantics.
{
  // Baseline map may omit keys; a draft '' over a missing baseline value is
  // "unchanged" (nothing to submit for that field).
  const base = { a: 'x', b: 'y ' }
  const draftSame = { a: 'x', b: 'y ' }
  check('dirty: identical is clean', changedGuidanceFields(base, draftSame, ['a', 'b']).length === 0)
  const draftEmptyOverMissing = { a: 'x', z: '' }
  check('dirty: empty draft over missing baseline is unchanged',
    !changedGuidanceFields({}, draftEmptyOverMissing, ['a', 'z']).includes('z'))
  const draftChanged = { a: 'X', b: 'y ' }
  check('dirty: only changed fields, server order',
    JSON.stringify(changedGuidanceFields(base, draftChanged, ['a', 'b'])) === '["a"]')
  const spaces = { a: ' x' }
  check('dirty: whitespace is a real change (no trim)',
    changedGuidanceFields({ a: 'x' }, spaces, ['a']).includes('a'))
  check('dirty: empty draft over empty baseline is unchanged',
    changedGuidanceFields({ a: '' }, { a: '' }, ['a']).length === 0)
  check('dirty: newline-only draft counts as changed',
    changedGuidanceFields({ a: 'x' }, { a: '\n' }, ['a']).includes('a'))
}

// 5. Stale-response invalidation: bump kills the old epoch (success, error
//    and finally branches must all treat it as dead).
{
  const g = createEpochGuard()
  const at = g.token()
  check('epoch: alive before bump', g.alive(at))
  g.bump()
  check('epoch: dead after bump', !g.alive(at))
  const at2 = g.token()
  check('epoch: new token alive and distinct', g.alive(at2) && at2 !== at)
  g.bump(); g.bump()
  check('epoch: multiple bumps invalidate once-removed too', !g.alive(at2))
}

// 6. Fixed error notices.
{
  const conflict = aiErrorNotice({ status: 409, code: 'VERSION_CONFLICT' }, 'fallback')
  check('notice: 409 keeps-id message fixed', typeof conflict === 'string' && conflict.includes('保留当前输入'))
  const validation = aiErrorNotice({ status: 422, code: 'VALIDATION_ERROR' }, 'fallback')
  check('notice: 422 fixed generic', validation === '保存未通过校验，请检查输入后重试。')
  check('notice: AUTH_REQUIRED silenced', aiErrorNotice({ status: 401, code: 'AUTH_REQUIRED' }, 'x') === null)
  const maskProbe = aiErrorNotice({ status: 503, code: 'AI_CONFIG_UNAVAILABLE' }, 'x')
  check('notice: 503 blames key material, not the supplier',
    maskProbe !== null && maskProbe.includes('加密材料') && maskProbe.includes('不是供应商连接问题'))
  const unknown = aiErrorNotice({ status: 418, code: 'SOMETHING_NEW' }, '读取失败')
  check('notice: unknown code falls back to safe text', unknown === '读取失败')
}

// 7. Ready wording: never claims connectivity; DECRYPT_UNAVAILABLE explains
//    the degraded-but-alive state.
{
  const ready = readyStatusText(true, null)
  check('ready: wording promises local only',
    ready.includes('本地配置可用') && ready.includes('尚未验证') && !ready.includes('连接成功'))
  const decrypt = readyStatusText(false, 'DECRYPT_UNAVAILABLE')
  check('ready: decrypt-unavailable is explained and non-blocking',
    decrypt.includes('加密配置不可用') && decrypt.includes('不影响'))
}

// 8. Task labels: exactly the seven seeded keys are mapped; list rendering
//    itself always uses server items (order/fields are never hardcoded).
{
  const names = ['daily_lesson_split', 'daily_process_adapt', 'daily_other_activities',
    'weekly_games', 'weekly_columns', 'weekly_theme_suggestion', 'weekly_materials']
  check('tasks: seven seeded labels resolvable',
    names.every((t) => isKnownTaskType(t) && taskDisplayName(t) !== t))
  check('tasks: unknown id falls back to itself',
    taskDisplayName('future_task') === 'future_task' && !isKnownTaskType('future_task'))
}

if (failures > 0) {
  console.error(`${failures}/${checks} directed checks FAILED`)
  process.exit(1)
}
console.log(`${checks} directed checks passed (secret omission/raw/clear JSON, dirty baselines, epoch invalidation, fixed notices, ready wording)`)
