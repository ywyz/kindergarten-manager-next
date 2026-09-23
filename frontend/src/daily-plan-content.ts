/**
 * Pure helpers for the I3 manual daily plan form: server content <-> editable
 * form model, save payload construction and I3 error message mapping.
 *
 * No defaults are invented for user content: sections the teacher never
 * touched stay absent from the save payload, empty text stays empty, and
 * group_id / game_id are only echoed when the server already issued them
 * (new objects are sent without IDs so the server generates them). The fixed
 * morning-exercise label is display-only in the form and is echoed back only
 * when the server already issued it, so adopted_content may stay {}.
 */

import type { AdoptedContent, AdoptedGame } from './types'

export const MORNING_EXERCISE_LABEL = '体能大循环'

export interface GameForm {
  game_id?: string
  name: string
}

export interface MorningGroupForm {
  group_id?: string
  group_kind: 'collective' | 'free_choice'
  games: GameForm[]
  focus_guidance: string
  shared_objectives: string
  guidance_points: string
}

export interface PostGroupForm {
  group_id?: string
  context_kind: 'area' | 'outdoor' | 'special_room'
  area: string
  games: GameForm[]
  focus_guidance: string
  objectives: string
  guidance: string
  support_strategy: string
}

export interface AfternoonForm {
  group_id?: string
  area: string
  games: GameForm[]
  observation_focus: string
  objectives: string
  guidance: string
  support_strategy: string
}

export interface PlanContentForm {
  /** Carried only when the server already issued it; no edit control, no default. */
  morning_exercise_label?: string
  morning_games: MorningGroupForm[]
  morning_talk: { topic: string; questions: string }
  group_activity: {
    theme: string
    objectives: string
    preparation: string
    key_points: string
    difficult_points: string
    process: string
  }
  post_group_games: PostGroupForm[]
  afternoon_outdoor: AfternoonForm
  reflection: string
}

function gameForms(games: AdoptedGame[] | null | undefined): GameForm[] {
  return (games || []).map((game) => ({
    ...(game.game_id ? { game_id: game.game_id } : {}),
    name: game.name ?? '',
  }))
}

export function emptyContentForm(): PlanContentForm {
  // No morning_exercise_label: the fixed label is display-only, never invented.
  return {
    morning_games: [],
    morning_talk: { topic: '', questions: '' },
    group_activity: {
      theme: '',
      objectives: '',
      preparation: '',
      key_points: '',
      difficult_points: '',
      process: '',
    },
    post_group_games: [],
    afternoon_outdoor: {
      area: '',
      games: [],
      observation_focus: '',
      objectives: '',
      guidance: '',
      support_strategy: '',
    },
    reflection: '',
  }
}

export function serverToForm(content: AdoptedContent | null | undefined): PlanContentForm {
  const c: AdoptedContent = content || {}
  return {
    ...(c.morning_exercise_label != null
      ? { morning_exercise_label: c.morning_exercise_label }
      : {}),
    morning_games: (c.morning_games || []).map((group) => ({
      ...(group.group_id ? { group_id: group.group_id } : {}),
      group_kind: group.group_kind,
      games: gameForms(group.games),
      focus_guidance: group.focus_guidance ?? '',
      shared_objectives: group.shared_objectives ?? '',
      guidance_points: group.guidance_points ?? '',
    })),
    morning_talk: {
      topic: c.morning_talk?.topic ?? '',
      questions: c.morning_talk?.questions ?? '',
    },
    group_activity: {
      theme: c.group_activity?.theme ?? '',
      objectives: c.group_activity?.objectives ?? '',
      preparation: c.group_activity?.preparation ?? '',
      key_points: c.group_activity?.key_points ?? '',
      difficult_points: c.group_activity?.difficult_points ?? '',
      process: c.group_activity?.process ?? '',
    },
    post_group_games: (c.post_group_games || []).map((group) => ({
      ...(group.group_id ? { group_id: group.group_id } : {}),
      context_kind: group.context_kind,
      area: group.area ?? '',
      games: gameForms(group.games),
      focus_guidance: group.focus_guidance ?? '',
      objectives: group.objectives ?? '',
      guidance: group.guidance ?? '',
      support_strategy: group.support_strategy ?? '',
    })),
    afternoon_outdoor: {
      ...(c.afternoon_outdoor?.group_id
        ? { group_id: c.afternoon_outdoor.group_id }
        : {}),
      area: c.afternoon_outdoor?.area ?? '',
      games: gameForms(c.afternoon_outdoor?.games),
      observation_focus: c.afternoon_outdoor?.observation_focus ?? '',
      objectives: c.afternoon_outdoor?.objectives ?? '',
      guidance: c.afternoon_outdoor?.guidance ?? '',
      support_strategy: c.afternoon_outdoor?.support_strategy ?? '',
    },
    reflection: c.reflection ?? '',
  }
}

function serialiseGames(games: GameForm[]): AdoptedGame[] {
  return games.map((game) => ({
    ...(game.game_id ? { game_id: game.game_id } : {}),
    name: game.name,
  }))
}

function hasAny(...values: string[]): boolean {
  return values.some((value) => value !== '')
}

/**
 * Build the adopted_content payload for save.
 *
 * The fixed "体能大循环" label is display-only: it is written back only when
 * the form already carries a server-issued morning_exercise_label, so an
 * empty form yields {}. Structural groups are included only when the teacher
 * actually has them in the form; scalar sections are included only when at
 * least one of their fields is non-empty, so an untouched plan is never
 * padded with empty structure. IDs issued by the server are echoed back; new
 * objects carry no client-generated IDs.
 */
export function buildAdoptedContent(form: PlanContentForm): AdoptedContent {
  const out: AdoptedContent = {}
  if (form.morning_exercise_label !== undefined) {
    out.morning_exercise_label = form.morning_exercise_label
  }

  if (form.morning_games.length > 0) {
    out.morning_games = form.morning_games.map((group) => ({
      ...(group.group_id ? { group_id: group.group_id } : {}),
      group_kind: group.group_kind,
      games: serialiseGames(group.games),
      focus_guidance: group.focus_guidance,
      shared_objectives: group.shared_objectives,
      guidance_points: group.guidance_points,
    }))
  }

  const talk = form.morning_talk
  if (talk.topic !== '' || talk.questions !== '') {
    out.morning_talk = { topic: talk.topic, questions: talk.questions }
  }

  const activity = form.group_activity
  if (
    hasAny(
      activity.theme,
      activity.objectives,
      activity.preparation,
      activity.key_points,
      activity.difficult_points,
      activity.process,
    )
  ) {
    out.group_activity = {
      theme: activity.theme,
      objectives: activity.objectives,
      preparation: activity.preparation,
      key_points: activity.key_points,
      difficult_points: activity.difficult_points,
      process: activity.process,
    }
  }

  if (form.post_group_games.length > 0) {
    out.post_group_games = form.post_group_games.map((group) => ({
      ...(group.group_id ? { group_id: group.group_id } : {}),
      context_kind: group.context_kind,
      area: group.area,
      games: serialiseGames(group.games),
      focus_guidance: group.focus_guidance,
      objectives: group.objectives,
      guidance: group.guidance,
      support_strategy: group.support_strategy,
    }))
  }

  const afternoon = form.afternoon_outdoor
  if (
    afternoon.games.length > 0 ||
    hasAny(
      afternoon.area,
      afternoon.observation_focus,
      afternoon.objectives,
      afternoon.guidance,
      afternoon.support_strategy,
    )
  ) {
    out.afternoon_outdoor = {
      ...(afternoon.group_id ? { group_id: afternoon.group_id } : {}),
      area: afternoon.area,
      games: serialiseGames(afternoon.games),
      observation_focus: afternoon.observation_focus,
      objectives: afternoon.objectives,
      guidance: afternoon.guidance,
      support_strategy: afternoon.support_strategy,
    }
  }

  if (form.reflection !== '') {
    out.reflection = form.reflection
  }

  return out
}

export function dailyPlanErrorMessage(err: unknown, fallback: string): string {
  const e = err as { status?: number; code?: string; message?: string }
  const codeMessages: Record<string, string> = {
    AUTH_REQUIRED: '登录已失效，请重新登录',
    FORBIDDEN: '没有权限执行此操作',
    DAILY_PLAN_NOT_FOUND: '日计划不存在',
    VERSION_CONFLICT: '内容版本冲突：他人已保存更新，请先处理冲突',
    VALIDATION_ERROR: '请求参数校验失败，请检查输入',
    OUTSIDE_TERM: '该日期不在学期范围内，不能创建日计划',
    DATE_NOT_ELIGIBLE: '该日期不是上课日，不能创建日计划',
    YEAR_NOT_COVERED: '该年份日历数据未就绪，请联系管理员配置后再试',
    SERVICE_UNAVAILABLE: '服务暂不可用，请稍后重试',
    WEEKLY_PLAN_SYNC_NOT_FOUND: '周计划同步投影不存在',
    CLASS_NOT_FOUND: '班级不存在',
  }
  if (e.code && codeMessages[e.code]) {
    return codeMessages[e.code]
  }
  const statusMessages: Record<number, string> = {
    401: '登录已失效，请重新登录',
    403: '没有权限执行此操作',
    404: '资源不存在',
    409: '数据冲突，请查看最新内容后重试',
    422: '请求参数校验失败，请检查输入',
    503: '服务暂不可用，请稍后重试',
  }
  if (e.status !== undefined && statusMessages[e.status]) {
    return statusMessages[e.status]
  }
  return e.message || fallback
}

export function isAuthError(err: unknown): boolean {
  const e = err as { status?: number; code?: string }
  return e?.status === 401 || e?.code === 'AUTH_REQUIRED'
}
