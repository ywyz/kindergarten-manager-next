/**
 * Pure local-date helpers for the Asia/Shanghai UI.
 *
 * These functions operate on calendar (year/month/day) components and never
 * convert through UTC, so month arithmetic stays correct regardless of the
 * host time zone offset.
 */

function pad(n: number): string {
  return n.toString().padStart(2, '0')
}

export function formatLocalDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function localMonthStart(): string {
  const now = new Date()
  return formatLocalDate(new Date(now.getFullYear(), now.getMonth(), 1))
}

export function parseLocalDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10))
  return new Date(y, m - 1, d)
}

export function monthRange(iso: string): { from: string; to: string } {
  const base = parseLocalDate(iso)
  const y = base.getFullYear()
  const m = base.getMonth()
  return {
    from: formatLocalDate(new Date(y, m, 1)),
    to: formatLocalDate(new Date(y, m + 1, 0)),
  }
}

export function shiftMonth(iso: string, delta: number): string {
  const base = parseLocalDate(iso)
  const y = base.getFullYear()
  const m = base.getMonth()
  return formatLocalDate(new Date(y, m + delta, 1))
}
