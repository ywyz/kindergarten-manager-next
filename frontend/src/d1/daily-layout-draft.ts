/**
 * Pure helpers for the daily-plan left-directory layout (2026-11-15).
 *
 * The page body is read-only. "编辑本栏" opens a modal that owns an independent
 * deep copy of the column; only an explicit confirm merges that one column back
 * into the live draft. Cancelling must leave the previous draft byte-equivalent,
 * so none of these helpers ever mutate the passed form/draft object.
 */

import type {
  MorningGroupForm,
  PlanContentForm,
} from '../daily-plan-content'

export type DailyLayoutSectionKey =
  | 'raw'
  | 'morning'
  | 'talk'
  | 'group'
  | 'post'
  | 'afternoon'
  | 'reflection'

export interface DailyLayoutDraft {
  /** Independent copy of the whole form; only the edited section is merged. */
  form: PlanContentForm
  /** Original lesson text is edited as a column of its own. */
  raw: string
  /** Reflection implementation material is not saved content, but it is
   * edited together with the reflection column and must survive cancel. */
  materials: string
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function cloneDailyLayoutForm(form: PlanContentForm): PlanContentForm {
  return clone(form)
}

export function cloneDailyLayoutDraft(
  form: PlanContentForm,
  raw: string,
  materials: string,
): DailyLayoutDraft {
  return {
    form: cloneDailyLayoutForm(form),
    raw: raw ?? '',
    materials: materials ?? '',
  }
}

/**
 * Merge exactly one column of the modal draft into a fresh copy of the live
 * form. Other columns keep whatever the current form holds (for example an AI
 * direct-fill that happened while the dialog was open in another column).
 */
export function applyDailyLayoutSection(
  draft: DailyLayoutDraft,
  current: PlanContentForm,
  section: DailyLayoutSectionKey,
): PlanContentForm {
  const next = cloneDailyLayoutForm(current)
  switch (section) {
    case 'raw':
      // Raw text is not part of the form; the caller applies `draft.raw`.
      return next
    case 'morning':
      next.morning_games = clone(draft.form.morning_games)
      return next
    case 'talk':
      next.morning_talk = clone(draft.form.morning_talk)
      return next
    case 'group':
      next.group_activity = clone(draft.form.group_activity)
      return next
    case 'post':
      next.post_group_games = clone(draft.form.post_group_games)
      return next
    case 'afternoon':
      next.afternoon_outdoor = clone(draft.form.afternoon_outdoor)
      return next
    case 'reflection':
      next.reflection = draft.form.reflection
      return next
  }
}

/**
 * Read-only morning selection, matching the existing Word/current rule:
 * among valid groups in stored order, the first with both a focus value and a
 * named game wins; otherwise the first group with a named game.
 */
export function dailyMorningGroupHasNamedGame(group: MorningGroupForm): boolean {
  return group.games.some((game) => (game.name ?? '').trim() !== '')
}

export function dailyMorningFocusGroupIndex(groups: MorningGroupForm[]): number {
  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index]
    if (group.group_kind !== 'collective' && group.group_kind !== 'free_choice') continue
    if ((group.focus_guidance ?? '').trim() !== '' && dailyMorningGroupHasNamedGame(group)) {
      return index
    }
  }
  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index]
    if (group.group_kind !== 'collective' && group.group_kind !== 'free_choice') continue
    if (dailyMorningGroupHasNamedGame(group)) return index
  }
  return -1
}

/** Historical non-focus details stay stored; the read pane only notes them. */
export function dailyMorningGroupHasHiddenDetails(group: MorningGroupForm): boolean {
  return (
    (group.focus_guidance ?? '').trim() !== ''
    || (group.shared_objectives ?? '').trim() !== ''
    || (group.guidance_points ?? '').trim() !== ''
  )
}

/**
 * Canonical value of the column currently being edited. Comparing the baseline
 * signature with the live draft tells the editor whether the modal holds
 * unsaved input (leave/close protection, AI-write protection).
 */
export function dailyLayoutDraftSignature(
  draft: DailyLayoutDraft,
  section: DailyLayoutSectionKey,
): string {
  switch (section) {
    case 'raw':
      return JSON.stringify({ raw: draft.raw })
    case 'morning':
      return JSON.stringify(draft.form.morning_games)
    case 'talk':
      return JSON.stringify(draft.form.morning_talk)
    case 'group':
      return JSON.stringify(draft.form.group_activity)
    case 'post':
      return JSON.stringify(draft.form.post_group_games)
    case 'afternoon':
      return JSON.stringify(draft.form.afternoon_outdoor)
    case 'reflection':
      return JSON.stringify({
        reflection: draft.form.reflection,
        materials: draft.materials,
      })
  }
}
