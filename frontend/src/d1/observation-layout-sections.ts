/**
 * Game observation layout helpers (2026-11-15 left-directory round).
 *
 * Section metadata, read-pane labels and section signatures for the
 * observation editor modal copy. Pure functions only: no API, Vue, DOM or
 * business semantics are changed here.
 */
import {
  EVALUATION_KEYS,
  EVALUATION_LABELS,
  type EvaluationKey,
  type ObservationForm,
} from './observation'

export type ObservationSectionKey =
  | 'basic'
  | 'subjects'
  | 'body'
  | 'evaluation'
  | 'support'
  | 'photos'
  | 'ai'

export interface ObservationSectionInfo {
  key: ObservationSectionKey
  label: string
  hint: string
  /** Text sections that open the independent modal copy. */
  editable: boolean
}

export const OBSERVATION_SECTIONS: ObservationSectionInfo[] = [
  {
    key: 'basic',
    label: '观察资料',
    hint: '日期、时间、园所班级、人数与统一年龄；学期归属单独确认。',
    editable: true,
  },
  {
    key: 'subjects',
    label: '对象与环境',
    hint: '重点观察幼儿按顺序保留，同名不合并；环境为本份文字。',
    editable: true,
  },
  {
    key: 'body',
    label: '观察正文',
    hint: '观察目标与观察记录完整保留换行；长文在栏内滚动，可打开“阅读 / 编辑”查看全文。',
    editable: true,
  },
  {
    key: 'evaluation',
    label: '评价分析 · 五领域',
    hint: '健康、语言、社会、科学、艺术五栏分别保留；未填写的栏目显示为未填写。',
    editable: true,
  },
  {
    key: 'support',
    label: '支持策略',
    hint: '支持策略正文单独成栏，便于阅读和编辑。',
    editable: true,
  },
  {
    key: 'photos',
    label: '有序照片',
    hint: '在独立照片管理弹窗中导入、排序、说明和移除；仍属于当前记录。',
    editable: false,
  },
  {
    key: 'ai',
    label: 'AI 生成与候选',
    hint: '生成四栏或单栏重写只产生候选；采用仍走预览与保存。',
    editable: false,
  },
]

export function observationSectionInfo(key: ObservationSectionKey): ObservationSectionInfo {
  return OBSERVATION_SECTIONS.find((section) => section.key === key) ?? OBSERVATION_SECTIONS[0]
}

export function observationSectionLabel(key: ObservationSectionKey): string {
  return observationSectionInfo(key).label
}

export function observationDisplay(value: string | null | undefined, empty = '（未填写）'): string {
  const text = value ?? ''
  return text.trim() ? text : empty
}

export function observationSubjectList(subjects: string[]): string[] {
  return subjects
    .map((name) => name.trim())
    .filter((name) => name.length > 0)
}

export function observationEvaluationRows(
  form: ObservationForm,
): Array<{ key: EvaluationKey; label: string; value: string }> {
  return EVALUATION_KEYS.map((key) => ({
    key,
    label: EVALUATION_LABELS[key],
    value: form.analysis_evaluation[key] ?? '',
  }))
}

function encode(parts: unknown[]): string {
  return JSON.stringify(parts)
}

/**
 * Signature of the values the modal would fill back for one section. The
 * modal stores the draft-side signature on open; a different current value
 * means another save/AI result arrived and needs a second explicit confirm.
 */
export function observationSectionSignature(
  key: ObservationSectionKey,
  form: ObservationForm,
): string {
  if (key === 'basic') {
    return encode([
      'basic',
      form.observation_date,
      form.start_time,
      form.end_time,
      form.school_name,
      form.class_name,
      form.observer_name,
      form.adult_count,
      form.child_count,
      form.age_years,
    ])
  }
  if (key === 'subjects') {
    return encode(['subjects', observationSubjectList(form.subjects), form.environment])
  }
  if (key === 'body') {
    return encode(['body', form.observation_goal, form.observation_process])
  }
  if (key === 'evaluation') {
    return encode(['evaluation', ...EVALUATION_KEYS.map((field) => form.analysis_evaluation[field] ?? '')])
  }
  if (key === 'support') {
    return encode(['support', form.support_strategy])
  }
  return encode(['readonly', key])
}

/** Field names copied back by 填回草稿 for each editable section. */
export const OBSERVATION_SECTION_FIELDS: Record<
  Exclude<ObservationSectionKey, 'photos' | 'ai'>,
  Array<keyof ObservationForm>
> = {
  basic: [
    'observation_date',
    'start_time',
    'end_time',
    'school_name',
    'class_name',
    'observer_name',
    'adult_count',
    'child_count',
    'age_years',
  ],
  subjects: ['subjects', 'environment'],
  body: ['observation_goal', 'observation_process'],
  evaluation: ['analysis_evaluation'],
  support: ['support_strategy'],
}
