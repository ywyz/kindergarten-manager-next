/**
 * D1 types: strictly mirror the local API schemas (backend/app/local).
 * The legacy weekly projection and account/admin fields are intentionally
 * absent. Adopted content reuses the reviewed v1 shape (no weekly fields).
 */

import type { AdoptedContent } from '../types'

export interface LocalProfile {
  id: string
  display_name: string
}

export interface LocalClassInfo {
  id: string
  name: string
  grade: 'small' | 'middle' | 'large'
}

export interface LocalTerm {
  id: string
  name: string
  start_date: string
  end_date: string
}

export interface LocalTermContext extends LocalTerm {
  current_calendar_revision_id: string
}

export interface LocalCalendarRevision {
  id: string
  revision_no: number
  library_version: string
}

export interface LocalContext {
  status: 'uninitialized' | 'ready'
  profile: LocalProfile | null
  school_name: string | null
  class: LocalClassInfo | null
  term: LocalTerm | null
  calendar_revision: LocalCalendarRevision | null
  config_version: number | null
  as_of_date: string | null
  terms: LocalTermContext[]
}

export interface PlanContent {
  id: string
  version: number
  raw_lesson_plan: string | null
  split_baseline: Record<string, unknown> | null
  adopted_content: AdoptedContent
  editor_id: string
  created_at: string
}

export interface DailyPlan {
  id: string
  class_id: string
  term_id: string
  plan_date: string
  week_number: number
  weekday: number
  calendar_revision_id: string
  creator_id: string
  creator_display_name: string | null
  current_content_id: string
  current_content_version: number
  content: PlanContent
  school_name: string | null
  class_name: string
  grade: string
  created_at: string
  updated_at: string
}

export interface CalendarDayItem {
  date: string
  term_id: string | null
  week_number: number | null
  weekday: number | null
  effective_state: 'teaching' | 'non_teaching' | 'unknown' | 'outside_term'
  date_eligible: boolean
  reason: string | null
  revision_id: string | null
  existing_plan_id: string | null
}

export interface CalendarPayload {
  from_date: string
  to_date: string
  items: CalendarDayItem[]
}

export interface PlanListItem {
  id: string
  plan_date: string
  week_number: number
  weekday: number
  creator_id: string
  creator_display_name: string | null
  current_content_version: number
  created_at: string
  updated_at: string
}

export interface PlanListPayload {
  items: PlanListItem[]
  total: number
  offset: number
  limit: number
}

export interface TermPlanListItem extends PlanListItem {
  class_id: string
  term_id: string
}

export interface TermPlanListPayload {
  items: TermPlanListItem[]
  total: number
  offset: number
  limit: number
}

// --- Configuration maintenance (spec §10.2) --------------------------------

export type Grade = 'small' | 'middle' | 'large'

/**
 * One class game location (D2 Q4 / product spec §9.1). ``guidance`` may be
 * ``null`` ("no text"); the game config is server-derived for the current
 * class, no client-selected class id.
 */
export interface GameLocation {
  kind: 'area' | 'special_room' | 'outdoor'
  name: string
  guidance: string | null
}

export type ConfigChange =
  | { kind: 'profile'; display_name: string; school_name: string | null }
  | { kind: 'current_class'; name: string; grade: 'small' | 'middle' | 'large' }
  | { kind: 'term_create'; name: string; start_date: string; end_date: string }
  | {
      kind: 'term_update'
      term_id: string
      name: string
      start_date: string
      end_date: string
    }
  | {
      kind: 'calendar_override'
      term_id: string
      date: string
      state: 'teaching' | 'non_teaching' | null
      reason: string | null
    }
  | {
      kind: 'class_games'
      locations: GameLocation[]
      game_scope: string | null
      guidance: string | null
    }

export interface ConfigCalendarDiffItem {
  date: string
  before_state: string
  after_state: string
  before_week: number | null
  after_week: number | null
  override_before: { state: string; reason: string } | null
  override_after: { state: string; reason: string } | null
}

export interface ConfigAffectedPlan {
  id: string
  plan_date: string
  term_id: string
  content_version: number
  stored_week_number: number | null
  proposed_week_number: number | null
  creation_eligible_after: boolean
  reasons: string[]
}

export interface ConfigImpact {
  retained_header_count: number
  affected_plans: ConfigAffectedPlan[]
  counts: {
    existing_plan_count?: number
    affected_plan_count?: number
    by_reason?: Record<string, number>
  }
}

export interface ConfigPreview {
  expected_config_version: number
  normalized_change: ConfigChange
  changed: boolean
  preview_token: string
  expires_at: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  calendar_diff: ConfigCalendarDiffItem[]
  impact: ConfigImpact
}

export interface ConfigApplyResult {
  status: 'applied' | 'unchanged'
  request_id: string
  config_version: number
  changed: boolean
  affected_plan_ids: string[]
  calendar_revision_id: string | null
  game_revision_id?: string | null
  replayed?: boolean | null
}

/** Read-only current class game configuration (D2 W2 hand-off)。 */
export interface ClassGames {
  class_id: string
  class_name: string
  grade: string
  config_version: number
  game_revision_id: string
  revision_no: number
  change: {
    kind: 'class_games'
    locations: GameLocation[]
    game_scope: string | null
    guidance: string | null
  }
}

// --- D2 AI configuration (engineering spec §5.1) ---------------------------

export type TaskType =
  | 'daily_lesson_split'
  | 'daily_process_adapt'
  | 'daily_other_activities'

/** GET/PATCH /api/local/ai/config (engineering spec §5.1 ``ConfigOut``). */
export interface AiConfig {
  ai_config_version: number
  protocol_id: string
  base_url: string | null
  model: string | null
  has_secret: boolean
  configured: boolean
  ready: boolean
  reason: string | null
}

export interface PromptField {
  key: string
  label: string
  default_text: string
}

/** One of the three daily personal prompts (engineering spec §5.1). */
export interface Prompt {
  task_type: TaskType
  personal_revision: number
  contract_version: number
  based_default_revision: number
  required_contract_version: number
  latest_default_revision: number
  guidance: Record<string, string>
  fields: PromptField[]
  rejected_default_revision: number | null
  adaptation_required: boolean
  orphaned_guidance: Record<string, string>
}

export interface PromptList {
  items: Prompt[]
}

export interface PromptDefault {
  task_type: TaskType
  contract_version: number
  default_revision: number
  guidance: Record<string, string>
  fields: PromptField[]
  bundle_hash: string
}

// --- D2 tasks (engineering spec §5.1) --------------------------------------

export interface AiTaskExecution {
  id: string
  generation: number
  ai_config_version: number
  personal_revision: number
  contract_version: number
  default_revision: number
  attempt_no: number | null
}

export interface AiTaskInputSummary {
  content_version: number | null
  target_grade: Grade | null
  dependency_hash: string | null
  /** Real backend type: a small object, never a string (R01/附加). */
  calendar_coverage_warning?: {
    coverage?: string
    unknown_dates?: string[]
    note?: string
  } | null
}

export interface AiTask {
  id: string
  plan_id: string
  task_type: TaskType
  status: string
  reason: string | null
  processing_certainty: string
  user_stop_requested: boolean
  created_at: string | null
  updated_at: string | null
  input_summary: AiTaskInputSummary
  execution: AiTaskExecution | null
  candidate_id: string | null
  allowed_actions: string[]
  retry_requires_ack: boolean
}

export interface AiTaskList {
  items: AiTask[]
  next_cursor: string | null
}

/** Read-only streaming progress for the task's current execution (display only). */
export interface AiTaskProgress {
  available: boolean
  task_id: string
  execution_id: string | null
  attempt_id: string | null
  attempt_no: number | null
  seq: number
  phase: string
  elapsed_ms: number
  last_data_age_ms: number | null
  reasoning: string
  content_chars: number
  truncated: boolean
}

// --- D2 candidates and adoption (engineering spec §5.1/§5.3) --------------

export type AdoptionState = 'eligible' | 'source_changed' | 'contract_obsolete'

export interface CandidateSource {
  content_version: number | null
  target_grade: string | null
  dependency_hash: string | null
  dependencies: Record<string, unknown>
  source_excerpt: Record<string, unknown>
}

export interface CandidateSummary {
  id: string
  plan_id: string
  task_id: string
  execution_id: string
  task_type: TaskType
  contract_version: number
  schema_version: number
  adoption_state: AdoptionState
  available_targets: string[]
  latest_content_version: number
  created_at: string | null
}

export interface CandidateDetail extends CandidateSummary {
  raw_candidate: Record<string, unknown>
  source: CandidateSource
}

export interface CandidateList {
  items: CandidateSummary[]
  next_cursor: string | null
}

export interface AdoptionPreview {
  preview_token: string
  expires_at: string
  content_version: number
  candidate_id: string
  selected_targets: string[]
  before: Record<string, unknown>
  after: Record<string, unknown>
  warnings: string[]
}

export interface AdoptionResult {
  changed: boolean
  plan_id: string
  content_id: string
  content_version: number
  candidate_id: string
  selected_targets: string[]
  request_id: string
}

/** GET /api/local/ai/operations/{request_id} (receipt read-back). */
export interface AiOperationReceipt {
  request_id: string
  operation_kind: string
  result: Record<string, unknown>
  committed_at: string | null
}
