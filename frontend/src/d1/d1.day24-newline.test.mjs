/** #24 AI text newline normalization (pure ai.ts helper). */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.join(d1Dir, 'ai.ts'), 'utf8')
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const module = { exports: {} }
vm.runInNewContext(js, { module, exports: module.exports, console })
const { normalizeAiText, adaptEditFromRaw, splitEditFromRaw } = module.exports

assert.equal(
  normalizeAiText('1. 导入\\n师：看看叶子。\\n2. 探索'),
  '1. 导入\n师：看看叶子。\n2. 探索',
)
assert.equal(normalizeAiText('师：看看叶子。\\n幼：绿色。'), '师：看看叶子。\n幼：绿色。')
assert.equal(
  normalizeAiText('1. 导入\\\\n师：看看叶子。\\\\n2. 探索'),
  '1. 导入\n师：看看叶子。\n2. 探索',
)
assert.equal(
  normalizeAiText('1. 记录字符串\\n1.5 厘米'),
  '1. 记录字符串\\n1.5 厘米',
)
assert.equal(
  normalizeAiText('1. 导入\\n师：先观察叶子。\\n请幼儿分组观察。\\n2. 小结'),
  '1. 导入\n师：先观察叶子。\n请幼儿分组观察。\n2. 小结',
)
assert.equal(
  normalizeAiText('先观察图片。\\n师：你看到了什么？'),
  '先观察图片。\n师：你看到了什么？',
)
for (const value of ['C:\\new\\file.txt', '报告\\n1.txt', 'line1\\nline2', 'a\\b']) {
  assert.equal(normalizeAiText(value), value)
}
assert.equal(
  normalizeAiText('师：比较 A/B 两张图。\\n幼：我喜欢第二张。'),
  '师：比较 A/B 两张图。\n幼：我喜欢第二张。',
)
assert.equal(
  normalizeAiText('师：读 \\name 后停顿。\\n请幼儿开始。'),
  '师：读 \\name 后停顿。\n请幼儿开始。',
)
assert.equal(
  normalizeAiText('师：请看 D:\\教学\\new.txt。\\n幼：看到了。'),
  '师：请看 D:\\教学\\new.txt。\n幼：看到了。',
)
assert.equal(
  normalizeAiText('师：打开 D:\\教学\\n图片。'),
  '师：打开 D:\\教学\\n图片。',
)
for (const value of [
  '师：请打开 D:\\教学\\new.txt。',
  '师：板书要保留 \\name 这个标记。',
  '师：请看 notes\\new.txt。',
]) {
  assert.equal(normalizeAiText(value), value)
}
{
  const started = Date.now()
  const value = '师：请看。' + '\\n师：继续。'.repeat(5000)
  const actual = normalizeAiText(value)
  assert.equal(actual.split('\n').length - 1, 5000)
  assert.ok(!actual.includes('\\n'))
  assert.ok(Date.now() - started < 2000, 'repeated escapes stay bounded')
}
assert.equal(
  adaptEditFromRaw({ process: '1. 导入\\n师：看看叶子。\\n2. 探索' }),
  '1. 导入\n师：看看叶子。\n2. 探索',
)
assert.equal(
  splitEditFromRaw({
    group_activity: { theme: '主题', process: '1. 导入\\n师：看看叶子。' },
  }).process,
  '1. 导入\n师：看看叶子。',
)
console.log('OK day24 newline: 9 checks')
