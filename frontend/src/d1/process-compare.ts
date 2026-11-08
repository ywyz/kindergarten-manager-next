/**
 * #21 process-step alignment for the age-adjustment preview.
 *
 * The backend returns the whole before/after process text. This module
 * splits numbered steps (or unnumbered paragraphs) and aligns them by
 * content, so a renumber caused by an insertion never marks every later
 * unchanged step as modified. Teacher speech, original characters and
 * internal newlines are preserved verbatim in each row.
 */

export type ProcessChange = 'unchanged' | 'modified' | 'added' | 'removed'

export interface ProcessStep {
  number: string | null
  body: string
  raw: string
}

export interface ProcessCompareRow {
  key: string
  label: string
  before: string | null
  after: string | null
  beforeNumber: string | null
  afterNumber: string | null
  change: ProcessChange
}

const NUMBER_RE = /^[ \t\u3000]*(?:[（(]\d{1,3}[)）]|\d{1,3}(?:[、)）]|[.．](?!\d)))[ \t\u3000]*/
const NUMBER_STRICT_RE = /^[ \t\u3000]*(?:[（(](\d{1,3})[)）]|(\d{1,3})(?:[、)）]|[.．](?!\d)))[ \t\u3000]*/

function numbered(line: string): string | null {
  const match = NUMBER_STRICT_RE.exec(line)
  return match ? (match[1] ?? match[2] ?? null) : null
}

function trimBlankEdges(text: string): string {
  return text.replace(/^\n+|\n+$/g, '').trimEnd()
}
export function splitProcessSteps(text: string): ProcessStep[] {
  if (!text || !text.trim()) return []
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const starts: { index: number; number: string }[] = []
  lines.forEach((line, index) => {
    const number = numbered(line)
    if (number !== null) starts.push({ index, number })
  })
  if (starts.length === 0) return paragraphs(lines)
  const steps: ProcessStep[] = []
  if (starts[0].index > 0) {
    const raw = trimBlankEdges(lines.slice(0, starts[0].index).join('\n'))
    if (raw.trim()) steps.push({ number: null, body: raw.trim(), raw })
  }
  for (let i = 0; i < starts.length; i += 1) {
    const start = starts[i].index
    const end = i + 1 < starts.length ? starts[i + 1].index : lines.length
    const raw = trimBlankEdges(lines.slice(start, end).join('\n'))
    const body = raw.replace(NUMBER_RE, '').trim()
    steps.push({ number: starts[i].number, body, raw })
  }
  return steps
}

function paragraphs(lines: string[]): ProcessStep[] {
  const blocks: string[] = []
  let current: string[] = []
  for (const line of lines) {
    if (line.trim() === '') {
      if (current.length) { blocks.push(current.join('\n').trim()); current = [] }
    } else current.push(line)
  }
  if (current.length) blocks.push(current.join('\n').trim())
  return blocks
    .filter((block) => block !== '')
    .map((raw) => ({ number: null, body: raw.trim(), raw }))
}

function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function bigrams(text: string): string[] {
  const out: string[] = []
  for (let i = 0; i + 1 < text.length; i += 1) out.push(text.slice(i, i + 2))
  return out
}

function similarity(left: string, right: string): number {
  const a = normalize(left)
  const b = normalize(right)
  if (a === b) return 1
  if (!a || !b) return 0
  if (a.length < 2 || b.length < 2) return 0
  const counts = new Map<string, number>()
  for (const gram of bigrams(a)) counts.set(gram, (counts.get(gram) ?? 0) + 1)
  let overlap = 0
  for (const gram of bigrams(b)) {
    const count = counts.get(gram) ?? 0
    if (count > 0) { overlap += 1; counts.set(gram, count - 1) }
  }
  return (2 * overlap) / (bigrams(a).length + bigrams(b).length)
}

const INSERT_COST = 0.6
const DELETE_COST = 0.6
const MIN_SIMILARITY = 0.45
/** A stable step title (its first body line) outranks raw similarity. */
function stepTitle(step: ProcessStep): string {
  return normalize(step.body.split('\n')[0] ?? '')
}

function pairCost(before: ProcessStep, after: ProcessStep): number {
  const sim = similarity(before.body, after.body)
  if (sim === 1) return 0
  const left = stepTitle(before)
  const right = stepTitle(after)
  if (left !== '' && left === right) return Math.min(1 - sim, 0.3)
  if (sim >= MIN_SIMILARITY) return 1 - sim
  return Infinity
}

export function alignProcess(beforeText: string, afterText: string): ProcessCompareRow[] {
  const before = splitProcessSteps(beforeText)
  const after = splitProcessSteps(afterText)
  if (before.length === 0 && after.length === 0) return []
  const n = before.length
  const m = after.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(Infinity))
  const back: string[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(''))
  dp[0][0] = 0
  for (let i = 0; i <= n; i += 1) {
    for (let j = 0; j <= m; j += 1) {
      const base = dp[i][j]
      if (!Number.isFinite(base)) continue
      if (i < n && j < m) {
        const extra = pairCost(before[i], after[j])
        if (Number.isFinite(extra)) {
          const cost = base + extra
          if (cost < dp[i + 1][j + 1]) { dp[i + 1][j + 1] = cost; back[i + 1][j + 1] = 'pair' }
        }
      }
      if (i < n && base + DELETE_COST < dp[i + 1][j]) { dp[i + 1][j] = base + DELETE_COST; back[i + 1][j] = 'del' }
      if (j < m && base + INSERT_COST < dp[i][j + 1]) { dp[i][j + 1] = base + INSERT_COST; back[i][j + 1] = 'ins' }
    }
  }
  const picks: { before: ProcessStep | null; after: ProcessStep | null; change: ProcessChange }[] = []
  let i = n
  let j = m
  while (i > 0 || j > 0) {
    const move = back[i][j]
    if (move === 'pair' && i > 0 && j > 0) {
      const b = before[i - 1]
      const a = after[j - 1]
      picks.push({ before: b, after: a, change: normalize(b.body) === normalize(a.body) ? 'unchanged' : 'modified' })
      i -= 1
      j -= 1
    } else if (move === 'del' && i > 0) {
      picks.push({ before: before[i - 1], after: null, change: 'removed' })
      i -= 1
    } else if (move === 'ins' && j > 0) {
      picks.push({ before: null, after: after[j - 1], change: 'added' })
      j -= 1
    } else {
      if (i > 0) { picks.push({ before: before[i - 1], after: null, change: 'removed' }); i -= 1 }
      else if (j > 0) { picks.push({ before: null, after: after[j - 1], change: 'added' }); j -= 1 }
    }
  }
  picks.reverse()
  if (
    before.length === 1 && after.length === 1 &&
    before[0].number === null && after[0].number === null
  ) {
    return [{
      key: 'row-1',
      label: '段落 1',
      before: before[0].raw,
      after: after[0].raw,
      beforeNumber: null,
      afterNumber: null,
      change: normalize(before[0].body) === normalize(after[0].body) ? 'unchanged' : 'modified',
    }]
  }
  return picks.map((pick, index) => ({
    key: `row-${index + 1}`,
    label: labelFor(pick.before, pick.after, index),
    before: pick.before?.raw ?? null,
    after: pick.after?.raw ?? null,
    beforeNumber: pick.before?.number ?? null,
    afterNumber: pick.after?.number ?? null,
    change: pick.change,
  }))
}

function labelFor(before: ProcessStep | null, after: ProcessStep | null, index: number): string {
  const number = after?.number ?? before?.number ?? null
  return number ? `环节 ${number}` : `段落 ${index + 1}`
}
