/**
 * D1 editor pure helpers: server→form→saveable projection, raw
 * normalization, dirty comparison and the temporary-key identity backfill
 * used for late-input saves (spec §11.1/§11.2).
 *
 * The saveable projection is exactly ``buildAdoptedContent(serverToForm(
 * server content))``; dirty comparison uses the same projection plus the
 * normalized raw text, so no display defaults, missing sections or
 * group/game identity semantics are invented. Array order is meaningful and
 * never sorted away.
 */

import {
  buildAdoptedContent,
  serverToForm,
  type PlanContentForm,
} from '../daily-plan-content.ts'
import type { AdoptedContent } from '../types'
import type { DailyPlan } from './types'

export interface EditorBaseline {
  /** Normalized raw text the baseline corresponds to. */
  raw: string
  /** Canonical JSON of the saveable payload projection. */
  content: string
  /** Content version the baseline corresponds to. */
  version: number
  planId: string
}

/** Unified empty/newline normalization for the raw lesson plan. */
export function normalizeRaw(value: string | null | undefined): string {
  return (value ?? '').replace(/\r\n?/g, '\n')
}

/** Canonical JSON of the saveable content projection for a form. */
export function contentProjection(form: PlanContentForm): string {
  return JSON.stringify(buildAdoptedContent(form))
}

/** Baseline from a server plan: serverToForm then buildAdoptedContent. */
export function baselineFromPlan(plan: DailyPlan): EditorBaseline {
  return {
    raw: normalizeRaw(plan.content.raw_lesson_plan),
    content: contentProjection(serverToForm(plan.content.adopted_content)),
    version: plan.current_content_version,
    planId: plan.id,
  }
}

export function isDirty(
  form: PlanContentForm,
  raw: string,
  baseline: EditorBaseline,
): boolean {
  return (
    normalizeRaw(raw) !== baseline.raw ||
    contentProjection(form) !== baseline.content
  )
}

/** Payload for PATCH: normalized raw plus the saveable content projection. */
export function buildSavePayload(
  form: PlanContentForm,
  raw: string,
): { raw_lesson_plan: string; adopted_content: AdoptedContent } {
  return {
    raw_lesson_plan: normalizeRaw(raw),
    adopted_content: buildAdoptedContent(form),
  }
}

// ---------------------------------------------------------------------------
// Late-input identity backfill (temporary keys, spec §11.2)
// ---------------------------------------------------------------------------

let tempKeyCounter = 0

export function newTempKey(): string {
  tempKeyCounter += 1
  return `tmp-${tempKeyCounter}-${Date.now().toString(36)}`
}

interface MaybeKeyed {
  _tmp?: string
}

/** Mark a freshly created group/game with an in-memory temporary key. */
export function markTemp<T extends object>(value: T): T {
  const keyed = value as T & MaybeKeyed
  if (keyed._tmp === undefined) keyed._tmp = newTempKey()
  return value
}

/**
 * Backfill server-issued group/game IDs onto the live form after a response
 * that raced with late input. Objects are correlated by the temporary key
 * captured before submit plus their array position; an object whose live
 * form no longer carries the submitted temporary key is never guessed —
 * nothing is assigned for it.
 *
 * Returns true when at least one ID was assigned.
 */
export function applyServerIdentity(
  liveForm: PlanContentForm,
  submittedForm: PlanContentForm,
  response: AdoptedContent,
): boolean {
  let assigned = false
  assigned =
    pairGroups(
      liveForm.morning_games,
      submittedForm.morning_games,
      response.morning_games ?? null,
    ) || assigned
  assigned =
    pairGroups(
      liveForm.post_group_games,
      submittedForm.post_group_games,
      response.post_group_games ?? null,
    ) || assigned
  assigned =
    pairAfternoon(
      liveForm.afternoon_outdoor,
      submittedForm.afternoon_outdoor,
      response.afternoon_outdoor ?? null,
    ) || assigned
  return assigned
}

type GroupLike = {
  group_id?: string
  games?: Array<{ game_id?: string }>
} & MaybeKeyed

function pairGames(
  live: Array<{ game_id?: string } & MaybeKeyed> | undefined,
  snap: Array<{ game_id?: string } & MaybeKeyed> | undefined,
  resp: unknown,
): boolean {
  if (!live || !snap || !Array.isArray(resp)) return false
  let assigned = false
  const count = Math.min(live.length, snap.length, resp.length)
  for (let i = 0; i < count; i += 1) {
    const liveGame = live[i]
    const snapGame = snap[i]
    const respGame = resp[i] as { game_id?: string | null } | undefined
    if (!liveGame || !snapGame || !respGame) continue
    if (snapGame._tmp === undefined || liveGame._tmp !== snapGame._tmp) continue
    if (liveGame.game_id === undefined && respGame.game_id) {
      liveGame.game_id = respGame.game_id
      assigned = true
    }
  }
  return assigned
}

function pairGroups(
  live: GroupLike[] | undefined,
  snap: GroupLike[] | undefined,
  resp: unknown,
): boolean {
  if (!live || !snap || !Array.isArray(resp)) return false
  let assigned = false
  const count = Math.min(live.length, snap.length, resp.length)
  for (let i = 0; i < count; i += 1) {
    const liveGroup = live[i]
    const snapGroup = snap[i]
    const respGroup = resp[i] as Record<string, unknown> | undefined
    if (!liveGroup || !snapGroup || !respGroup) continue
    if (snapGroup._tmp !== undefined && liveGroup._tmp === snapGroup._tmp) {
      const respId = respGroup.group_id
      if (liveGroup.group_id === undefined && typeof respId === 'string') {
        liveGroup.group_id = respId
        assigned = true
      }
    }
    if (pairGames(liveGroup.games, snapGroup.games, respGroup.games)) {
      assigned = true
    }
  }
  return assigned
}

function pairAfternoon(
  live: GroupLike,
  snap: GroupLike,
  resp: unknown,
): boolean {
  if (!resp || typeof resp !== 'object') return false
  const respObject = resp as Record<string, unknown>
  let assigned = false
  if (snap._tmp !== undefined && live._tmp === snap._tmp) {
    const respId = respObject.group_id
    if (live.group_id === undefined && typeof respId === 'string') {
      live.group_id = respId
      assigned = true
    }
  }
  if (pairGames(live.games, snap.games, respObject.games)) {
    assigned = true
  }
  return assigned
}

/**
 * Strip group/game IDs that no longer exist in the server's displayed
 * current version (explicit conflict resubmission, spec §11.2 #4): the
 * affected object is submitted as a new object (no ID) so the server issues
 * a fresh one. Text, order and group structure are never dropped and IDs are
 * never guessed by name.
 */
export function stripDeadIdentities(
  payload: AdoptedContent,
  serverCurrent: AdoptedContent,
): AdoptedContent {
  const liveGroups = new Set<string>()
  const liveGames = new Set<string>()
  collectIds(serverCurrent, liveGroups, liveGames)
  const walkGroups = (groups: unknown): unknown => {
    if (!Array.isArray(groups)) return groups
    return groups.map((group) => {
      const out: Record<string, unknown> = { ...(group as object) }
      if (typeof out.group_id === 'string' && !liveGroups.has(out.group_id)) {
        delete out.group_id
      }
      const games = out.games
      if (Array.isArray(games)) {
        out.games = games.map((game) => {
          const copy: Record<string, unknown> = { ...(game as object) }
          if (
            typeof copy.game_id === 'string' &&
            !liveGames.has(copy.game_id)
          ) {
            delete copy.game_id
          }
          return copy
        })
      }
      return out
    })
  }
  const out: AdoptedContent = { ...payload }
  out.morning_games = walkGroups(
    payload.morning_games,
  ) as AdoptedContent['morning_games']
  out.post_group_games = walkGroups(
    payload.post_group_games,
  ) as AdoptedContent['post_group_games']
  if (payload.afternoon_outdoor) {
    const afternoon = { ...payload.afternoon_outdoor } as Record<
      string,
      unknown
    >
    if (
      typeof afternoon.group_id === 'string' &&
      !liveGroups.has(afternoon.group_id)
    ) {
      delete afternoon.group_id
    }
    const games = afternoon.games
    if (Array.isArray(games)) {
      afternoon.games = games.map((game) => {
        const copy: Record<string, unknown> = { ...(game as object) }
        if (typeof copy.game_id === 'string' && !liveGames.has(copy.game_id)) {
          delete copy.game_id
        }
        return copy
      })
    }
    out.afternoon_outdoor =
      afternoon as unknown as AdoptedContent['afternoon_outdoor']
  }
  return out
}

function collectIds(
  content: AdoptedContent,
  groups: Set<string>,
  games: Set<string>,
): void {
  const sections: Array<Array<Record<string, unknown>> | null | undefined> = [
    content.morning_games as
      | Array<Record<string, unknown>>
      | null
      | undefined,
    content.post_group_games as
      | Array<Record<string, unknown>>
      | null
      | undefined,
  ]
  const afternoon = content.afternoon_outdoor as
    | Record<string, unknown>
    | null
    | undefined
  if (afternoon) sections.push([afternoon])
  for (const section of sections) {
    for (const group of section ?? []) {
      if (typeof group.group_id === 'string') groups.add(group.group_id)
      for (const game of (group.games as Array<Record<string, unknown>>) ?? []) {
        if (typeof game.game_id === 'string') games.add(game.game_id)
      }
    }
  }
}
