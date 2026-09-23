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
    /** I4 CONFIRM_ACK_REQUIRED carries the latest recomputed facts. */
    facts?: WeeklyPlanFacts
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

// --- I4 manual weekly plan -------------------------------------------------
// Strictly mirrors the backend I4 schemas (WeeklyPlan*Out / WeeklyPlan*In).
// Orthogonal dimensions stay separate: confirmation_status, missing,
// stale_sources and projection_pending are never collapsed into one status.

export type WeeklyPlanConfirmationStatus =
  | 'never_confirmed'
  | 'draft_ahead'
  | 'draft_current'

export type OutdoorSlotKey = 'collective_1' | 'collective_2' | 'free_choice_1'

export type WeeklyColumnKey =
  | 'key_week_focus'
  | 'environment_setup'
  | 'habit_culture'
  | 'home_cooperation'

export type DeterministicField = 'morning_talk_topic' | 'group_activity_theme'

export interface WeeklyPlanListItem {
  id: string
  term_id: string
  week_number: number
  creator_id: string
  owner_id: string
  draft_version: number
  confirmed_version: number | null
  needs_confirm: boolean
  updated_at: string
}

export interface WeeklyPlanList {
  items: WeeklyPlanListItem[]
  total: number
  offset: number
  limit: number
}

export interface DeterministicSource {
  daily_plan_id: string | null
  content_id: string | null
  content_version: number | null
  morning_talk_topic: string | null
  group_activity_theme: string | null
}

export interface DeterministicOverride {
  morning_talk_topic: string | null
  group_activity_theme: string | null
}

export interface DeterministicEffective {
  morning_talk_topic: string | null
  group_activity_theme: string | null
}

export interface DeterministicRow {
  date: string
  day_state: 'teaching' | 'rest'
  plan_state: 'saved' | 'no_plan' | 'none_required'
  source: DeterministicSource
  override: DeterministicOverride
  effective: DeterministicEffective
}

export interface OutdoorSlotDailyPlan {
  source_kind: 'daily_plan'
  manual_item_id?: string | null
  daily_plan_id: string
  content_id: string
  content_version: number
  group_id: string
  game_id: string
  name: string
  shared_objectives?: string | null
  guidance_points?: string | null
  focus_guidance?: string | null
}

/** manual_item_id is null only while creating a new manual entry (server issues it). */
export interface OutdoorSlotManual {
  source_kind: 'manual'
  manual_item_id: string | null
  daily_plan_id: null
  content_id: null
  content_version: null
  group_id: null
  game_id: null
  name: string
  shared_objectives?: string | null
  guidance_points?: string | null
  focus_guidance?: string | null
}

export type OutdoorSlot = OutdoorSlotDailyPlan | OutdoorSlotManual | null

export interface FocusArea {
  source_kind: 'daily_plan'
  manual_item_id?: null
  daily_plan_id: string
  content_id: string
  content_version: number
  group_id: string
  game_id: string
  context_kind: 'area' | 'outdoor' | 'special_room'
  area: string | null
  name: string
  objectives: string | null
  guidance: string | null
  support_strategy: string | null
}

export interface WeeklyColumns {
  key_week_focus: string
  environment_setup: string
  habit_culture: string
  home_cooperation: string
}

export interface WeeklyPlanContent {
  theme: string
  deterministic: DeterministicRow[]
  outdoor_game_slots: Record<OutdoorSlotKey, OutdoorSlot>
  focus_area: FocusArea | null
  weekly_columns: WeeklyColumns
  materials: null
}

export interface WeeklyMissingFact {
  kind: string
  date?: string
  field?: string
  slot?: string
  daily_plan_id?: string | null
  content_id?: string | null
  content_version?: number | null
  group_id?: string | null
  game_id?: string | null
}

export interface WeeklyStaleSide {
  content_id: string | null
  content_version: number | null
}

export interface WeeklyStaleSource {
  slot: string
  date?: string
  group_id?: string | null
  game_id?: string | null
  draft: WeeklyStaleSide
  current: WeeklyStaleSide
  daily_plan_id?: string | null
  current_daily_plan_id?: string | null
  current_item_exists?: boolean
}

export interface WeeklyPlanFacts {
  missing: WeeklyMissingFact[]
  stale_sources: WeeklyStaleSource[]
  ack_missing?: boolean
  ack_stale?: boolean
  note?: string | null
}

export interface RefreshedSource {
  slot: string
  kind?: string
  date?: string
  daily_plan_id?: string | null
  group_id?: string | null
  game_id?: string | null
  from?: {
    content_id?: string | null
    content_version?: number | null
    daily_plan_id?: string | null
  } | null
  to?: {
    content_id?: string | null
    content_version?: number | null
    daily_plan_id?: string | null
  } | null
  missing?: boolean
  current_item_exists?: boolean
}

export interface SourceCandidate {
  daily_plan_id: string
  content_id: string
  content_version: number
  date: string
  source_kind: 'daily_plan'
  source_section: 'morning_games' | 'post_group_games'
  category: 'collective' | 'free_choice' | 'focus'
  group_kind?: 'collective' | 'free_choice' | null
  context_kind?: 'area' | 'outdoor' | 'special_room' | null
  area?: string | null
  group_id: string
  game_id: string
  name: string
  shared_objectives?: string | null
  guidance_points?: string | null
  focus_guidance?: string | null
  objectives?: string | null
  guidance?: string | null
  support_strategy?: string | null
}

export interface WeeklyPlanDraft {
  id: string
  version: number
  content: WeeklyPlanContent
  audit: Record<string, unknown> | null
  editor_id: string
  editor_role: 'owner' | 'admin'
  created_at: string
}

export interface WeeklyPlanConfirmedSummary {
  version: number
  draft_version: number
  confirmed_by: string
  facts: WeeklyPlanFacts
  created_at: string
}

export interface WeeklyPlanConfirmation extends WeeklyPlanConfirmedSummary {
  id: string
  weekly_plan_id: string
  content: WeeklyPlanContent
}

export interface WeeklyPlanConfirmationList {
  items: WeeklyPlanConfirmedSummary[]
  total: number
}

export interface WeeklyPlanDetail {
  id: string
  class_id: string
  term_id: string
  week_number: number
  creator_id: string
  owner_id: string
  school_name: string | null
  class_name: string
  grade: string
  header_teacher_names: string[]
  caregiver_name: string | null
  confirmation_status: WeeklyPlanConfirmationStatus
  needs_confirm: boolean
  draft: WeeklyPlanDraft
  confirmed: WeeklyPlanConfirmedSummary | null
  missing: WeeklyMissingFact[]
  stale_sources: WeeklyStaleSource[]
  projection_pending: boolean
  source_candidates: SourceCandidate[]
  can_edit: boolean
  can_confirm: boolean
  refreshed_sources: RefreshedSource[] | null
  created_at: string
  updated_at: string
}

export interface WeeklyPlanCreateIn {
  term_id: string
  week_number: number
  theme?: string | null
  // Teachers must omit class_id entirely (even null is a 422); admins never
  // create, so the frontend never sends class_id on this route.
}

export interface WeeklyPlanPatchIn {
  expected_draft_version: number
  theme?: string | null
  deterministic_overrides?: Record<
    string,
    Partial<DeterministicOverride> | null
  >
  outdoor_game_slots?: Partial<Record<OutdoorSlotKey, OutdoorSlot>>
  focus_area?: FocusArea | null
  weekly_columns?: Partial<WeeklyColumns>
}

export interface WeeklyPlanRefreshIn {
  expected_draft_version: number
}

export interface WeeklyPlanConfirmIn {
  expected_draft_version: number
  acknowledge_missing: boolean
  acknowledge_stale: boolean
  note?: string | null
}
