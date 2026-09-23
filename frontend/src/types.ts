export interface Account {
  id: string
  username: string
  display_name: string | null
  role: 'admin' | 'teacher'
  is_active: boolean
  version: number
}

export type Grade = 'small' | 'middle' | 'large'

export interface Me {
  account: Account
  class_id: string | null
  assignment_status: string
  can_prepare: boolean
}

export interface ClassInfo {
  id: string
  name: string
  grade: Grade
  header_teacher_names: string[]
  caregiver_name: string | null
  version: number
}

export interface AssignedTeacher {
  id: string
  username: string
  display_name: string | null
  version: number
}

export interface ClassDetail extends ClassInfo {
  assigned_teachers: AssignedTeacher[]
}

export interface TeacherListItem extends Account {
  class_id: string | null
  assignment_status: string
}

export interface SchoolSettings {
  id: string
  school_name: string | null
  version: number
  schedule_version: number
}

export interface ConfigurationChange {
  id: string
  kind: string
  target_id: string
  base_versions: Record<string, unknown>
  candidate: Record<string, unknown> | null
  changes: Array<{ field: string; old: unknown; new: unknown }>
  impact: Record<string, unknown>
  blockers: string[]
  expires_at: string
  status: string
  applied_at: string | null
  result_reference: string | null
}

export interface Term {
  id: string
  name: string
  start_date: string
  end_date: string
  version: number
  calendar_revision_id: string | null
}

export interface CalendarDay {
  date: string
  term_id: string | null
  term_version: number | null
  calendar_revision_id: string | null
  week_number: number | null
  week_start: string | null
  weekday: number | null
  base_state: string | null
  override_state: string | null
  effective_state: string
  source: string
  date_eligible: boolean
  reason: string | null
  reason_code: string | null
}

export interface Calendar {
  from_date: string
  to_date: string
  schedule_version: number
  items: CalendarDay[]
}

export interface ClassContext {
  class: ClassInfo
  school_name: string | null
  school_version: number
}

export interface ErrorBody {
  error: {
    code: string
    message: string
    fields?: Record<string, string>
  }
}

// --- I3 manual daily plan -------------------------------------------------
// Strictly mirrors backend DailyPlanOut / content schemas. Soft-delete
// columns (deleted_at / deleted_by) are intentionally absent (I3 decision B).

export interface AdoptedGame {
  game_id?: string
  name: string
}

export interface AdoptedMorningGroup {
  group_id?: string
  group_kind: 'collective' | 'free_choice'
  games: AdoptedGame[]
  focus_guidance?: string | null
  shared_objectives?: string | null
  guidance_points?: string | null
}

export interface AdoptedMorningTalk {
  topic?: string | null
  questions?: string | null
}

export interface AdoptedGroupActivity {
  theme?: string | null
  objectives?: string | null
  preparation?: string | null
  key_points?: string | null
  difficult_points?: string | null
  process?: string | null
}

export interface AdoptedPostGroup {
  group_id?: string
  context_kind: 'area' | 'outdoor' | 'special_room'
  area?: string | null
  games: AdoptedGame[]
  focus_guidance?: string | null
  objectives?: string | null
  guidance?: string | null
  support_strategy?: string | null
}

export interface AdoptedAfternoonOutdoor {
  group_id?: string
  area?: string | null
  games: AdoptedGame[]
  observation_focus?: string | null
  objectives?: string | null
  guidance?: string | null
  support_strategy?: string | null
}

export interface AdoptedContent {
  morning_exercise_label?: string | null
  morning_games?: AdoptedMorningGroup[] | null
  morning_talk?: AdoptedMorningTalk | null
  group_activity?: AdoptedGroupActivity | null
  post_group_games?: AdoptedPostGroup[] | null
  afternoon_outdoor?: AdoptedAfternoonOutdoor | null
  reflection?: string | null
}

export interface DailyPlanContent {
  id: string
  version: number
  raw_lesson_plan: string | null
  split_baseline: Record<string, unknown> | null
  adopted_content: AdoptedContent
  editor_id: string
  created_at: string
}

export interface WeeklySyncSummary {
  status: string
  has_pending_projection: boolean
  saved_dates: string[]
  missing_dates: string[]
}

export interface DailyPlan {
  id: string
  class_id: string
  term_id: string
  plan_date: string
  week_number: number
  weekday: number
  creator_id: string
  creator_display_name: string | null
  current_content_id: string
  current_content_version: number
  content: DailyPlanContent
  school_name: string | null
  class_name: string
  grade: string
  weekly_sync_state: WeeklySyncSummary
  created_at: string
  updated_at: string
}

export interface DailyPlanCreateIn {
  plan_date: string
  class_id?: string
  raw_lesson_plan?: string | null
  adopted_content?: AdoptedContent
}

export interface DailyPlanPatchIn {
  expected_content_version: number
  raw_lesson_plan?: string | null
  adopted_content?: AdoptedContent
}
