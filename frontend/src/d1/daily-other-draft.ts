/**
 * Direct-fill helpers for one successful daily "other activities" generation.
 *
 * The teacher asked that a successful generation enter the current editable
 * draft directly, with no second candidate preview/adoption step. These pure
 * helpers only translate the frozen candidate output into the existing form
 * sections; they never save, never allocate server ids and never touch the
 * collective activity or reflection, which are outside this task's output.
 */
import type {
  AfternoonForm,
  MorningGroupForm,
  PlanContentForm,
  PostGroupForm,
} from '../daily-plan-content'

export const OTHER_BOARD_NAMES = [
  'morning_games',
  'morning_talk',
  'post_group_games',
  'afternoon_outdoor',
] as const

export type OtherBoardName = (typeof OTHER_BOARD_NAMES)[number]

export interface OtherFillResult {
  form: PlanContentForm
  appliedBoards: OtherBoardName[]
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function gamesFrom(value: unknown): { name: string }[] {
  return asArray(value)
    .map((item) => ({ name: asString(asRecord(item).name) }))
    .filter((game) => game.name !== '')
}

function hasBoard(
  raw: Record<string, unknown>,
  availableTargets: readonly string[],
  board: OtherBoardName,
): boolean {
  return raw[board] != null && availableTargets.includes(board)
}

/** Only the boards actually provided by this candidate may change the draft. */
export function otherBoardsProvided(
  raw: Record<string, unknown>,
  availableTargets: readonly string[],
): OtherBoardName[] {
  return OTHER_BOARD_NAMES.filter((board) =>
    hasBoard(raw, availableTargets, board),
  )
}

/**
 * Apply the generated boards to the current form without mutating the input.
 * A missing board is omitted (the saved text stays unchanged), matching the
 * product rule that an ungenerated board never clears existing content.
 */
export function applyOtherCandidateToForm(
  form: PlanContentForm,
  raw: Record<string, unknown>,
  availableTargets: readonly string[],
): OtherFillResult {
  const provided = otherBoardsProvided(raw, availableTargets)
  const next: PlanContentForm = {
    ...form,
    morning_games: form.morning_games.map((group) => ({
      ...group,
      games: group.games.map((game) => ({ ...game })),
    })),
    morning_talk: { ...form.morning_talk },
    group_activity: { ...form.group_activity },
    post_group_games: form.post_group_games.map((group) => ({
      ...group,
      games: group.games.map((game) => ({ ...game })),
    })),
    afternoon_outdoor: {
      ...form.afternoon_outdoor,
      games: form.afternoon_outdoor.games.map((game) => ({ ...game })),
    },
    reflection: form.reflection,
  }

  if (provided.includes('morning_games')) {
    const groups = asArray(raw.morning_games).map((item): MorningGroupForm => {
      const group = asRecord(item)
      return {
        group_kind: group.group_kind === 'free_choice' ? 'free_choice' : 'collective',
        games: gamesFrom(group.games),
        focus_guidance: asString(group.focus_guidance),
        shared_objectives: asString(group.shared_objectives),
        guidance_points: asString(group.guidance_points),
      }
    })
    if (groups.length > 0) next.morning_games = groups
  }

  if (provided.includes('morning_talk')) {
    const talk = asRecord(raw.morning_talk)
    next.morning_talk = {
      topic: asString(talk.topic),
      questions: asString(talk.questions),
    }
  }

  if (provided.includes('post_group_games')) {
    const groups = asArray(raw.post_group_games).map((item): PostGroupForm => {
      const group = asRecord(item)
      const kind = group.context_kind
      return {
        context_kind:
          kind === 'outdoor' || kind === 'special_room' ? kind : 'area',
        area: asString(group.area),
        games: gamesFrom(group.games),
        focus_guidance: asString(group.focus_guidance),
        objectives: asString(group.objectives),
        guidance: asString(group.guidance),
        support_strategy: asString(group.support_strategy),
      }
    })
    if (groups.length > 0) next.post_group_games = groups
  }

  if (provided.includes('afternoon_outdoor')) {
    const afternoon = asRecord(raw.afternoon_outdoor)
    next.afternoon_outdoor = {
      area: asString(afternoon.area),
      games: gamesFrom(afternoon.games),
      observation_focus: asString(afternoon.observation_focus),
      objectives: asString(afternoon.objectives),
      guidance: asString(afternoon.guidance),
      support_strategy: asString(afternoon.support_strategy),
    } satisfies AfternoonForm
  }

  return { form: next, appliedBoards: provided }
}
