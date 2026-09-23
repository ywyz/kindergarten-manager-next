<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDialog,
  ElMessage,
  ElTag,
} from 'element-plus'
import type { ConfigurationChange } from '../types'
import * as api from '../api'

const props = defineProps<{
  modelValue: boolean
  change: ConfigurationChange | null
  title?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'applied', change: ConfigurationChange): void
  (e: 'stale'): void
  (e: 're-preview'): void
}>()

const applying = ref(false)
const applyError = ref('')

watch(() => props.change?.id, () => {
  applyError.value = ''
})

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

interface DiffRow {
  label: string
  old: string
  new: string
  week: string
  source: string
  isDay: boolean
}

const STATE_LABEL: Record<string, string> = {
  teaching: '教学',
  non_teaching: '休息',
  unknown: '未知',
}

const FIELD_LABEL: Record<string, string> = {
  school_name: '园所名称',
  name: '名称',
  grade: '年级',
  header_teacher_names: '表头教师',
  caregiver_name: '保育员',
  start_date: '开始日期',
  end_date: '结束日期',
  base_state: '默认状态',
  base_library_version: '日历库版本',
  override_state: '例外状态',
  override_reason: '例外原因',
  effective_state: '有效状态',
}

const GRADE_LABEL: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

function fieldText(field: string): { label: string; isDay: boolean } {
  if (field.startsWith('day:')) {
    const parts = field.split(':')
    const datePart = parts[1]
    const sub = parts[2] ? FIELD_LABEL[parts[2]] || parts[2] : '有效状态'
    return { label: `${datePart} · ${sub}`, isDay: true }
  }
  return { label: FIELD_LABEL[field] || field, isDay: false }
}

function stateValue(v: unknown, field: string): string {
  if (v === null || v === undefined || v === '') return '（空）'
  if (field.includes('grade') && typeof v === 'string' && GRADE_LABEL[v]) {
    return GRADE_LABEL[v]
  }
  if (typeof v === 'string' && STATE_LABEL[v]) return STATE_LABEL[v]
  if (Array.isArray(v)) return v.length ? v.join('、') : '（空）'
  return String(v)
}

const diffRows = computed<DiffRow[]>(() => {
  const change = props.change
  if (!change) return []
  return change.changes.map((c) => {
    const meta = fieldText(c.field)
    const extra = c as Record<string, unknown>
    return {
      label: meta.label,
      old: stateValue(c.old, c.field),
      new: stateValue(c.new, c.field),
      week: (extra.week_label as string) || '',
      source: (extra.source as string) || '',
      isDay: meta.isDay,
    }
  })
})

const blocked = computed(() =>
  (props.change?.blockers || []).includes('DEPENDENCY_NOT_READY'),
)

const stale = computed(
  () =>
    applyError.value.includes('预览已过期') ||
    applyError.value.includes('数据已变化'),
)

const impact = computed<Record<string, unknown>>(
  () => props.change?.impact || {},
)

const impactEntries = computed(() => {
  const labels: Record<string, string> = {
    assigned_teacher_count: '实际受影响教师数',
    day_count: '日期总数',
    unknown_day_count: '未知日数',
    override_added: '新增例外',
    override_removed: '撤销例外',
    removed_to_unknown: '撤销后变为未知',
    unknown_resolved: '解决未知日',
    changed_day_count: '发生变化日数',
    masked_default_changes: '被例外遮盖的默认变化',
    week_shift_count: '周次变化日数',
    removed_override_dates: '移除的例外日期',
  }
  return Object.entries(impact.value)
    .filter(([k]) => k !== 'plan_impact_status')
    .map(([k, v]) => ({
      label: labels[k] || k,
      value: Array.isArray(v) ? (v.length ? v.join('、') : '无') : String(v),
    }))
})

function sourceTag(source: string): string {
  if (source === 'admin_exception') return '管理员例外'
  if (source === 'calendar_library') return '日历库'
  if (source === 'unknown') return '未知'
  return source
}

async function confirmApply() {
  if (!props.change || blocked.value) return
  applying.value = true
  applyError.value = ''
  try {
    await api.applyConfigurationChange(props.change.id)
    ElMessage.success('已生效')
    emit('applied', props.change)
    visible.value = false
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 409) {
      applyError.value =
        e.code === 'PREVIEW_EXPIRED'
          ? '预览已过期，请关闭后重新生成预览'
          : '数据版本已变化，当前预览已失效；请关闭后重新预览'
      ElMessage.warning(applyError.value)
      emit('stale')
    } else {
      ElMessage.error(e.message || '操作失败')
    }
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="title || '变更预览与确认'"
    width="640px"
  >
    <template v-if="change">
      <div class="diff-list">
        <div v-for="(row, i) in diffRows" :key="i" class="diff-row">
          <div class="diff-head">
            <span class="diff-label">{{ row.label }}</span>
            <el-tag v-if="row.isDay && row.week" size="small" type="info">
              {{ row.week }}
            </el-tag>
            <el-tag
              v-if="row.isDay && row.source"
              size="small"
              :type="row.source === 'admin_exception' ? 'warning' : 'success'"
            >
              {{ sourceTag(row.source) }}
            </el-tag>
          </div>
          <div class="diff-values">
            <span class="old">{{ row.old }}</span>
            <span class="arrow">→</span>
            <span class="new">{{ row.new }}</span>
          </div>
        </div>
      </div>

      <div class="meta">
        <div v-for="(entry, i) in impactEntries" :key="i">
          {{ entry.label }}：{{ entry.value }}
        </div>
        <div>
          计划影响状态：
          {{ impact.plan_impact_status === 'not_applicable_before_first_plan'
            ? '尚未进入有计划阶段'
            : impact.plan_impact_status }}
        </div>
      </div>

      <el-alert
        v-if="blocked"
        title="该变更需要计划影响处理能力，当前阶段暂不能应用"
        type="warning"
        :closable="false"
      />
      <el-alert
        v-if="applyError"
        :title="applyError"
        type="error"
        :closable="false"
        style="margin-top: 8px"
      />
    </template>

    <template #footer>
      <el-button @click="visible = false">
        {{ stale ? '关闭' : '取消' }}
      </el-button>
      <el-button
        v-if="stale"
        type="primary"
        @click="emit('re-preview')"
      >
        重新预览
      </el-button>
      <el-button
        v-else
        type="primary"
        :disabled="blocked"
        :loading="applying"
        @click="confirmApply"
      >
        确认生效
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.diff-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 12px;
}
.diff-row { padding: 6px 0; border-bottom: 1px dashed #ebeef5; }
.diff-row:last-child { border-bottom: none; }
.diff-head { display: flex; align-items: center; gap: 8px; }
.diff-label { color: #303133; font-weight: 500; }
.diff-values { margin-top: 4px; color: #606266; font-size: 0.9rem; }
.old { color: #909399; }
.arrow { margin: 0 8px; color: #c0c4cc; }
.new { color: #409eff; font-weight: 500; }
.meta {
  margin: 12px 0;
  color: #606266;
  font-size: 0.9rem;
  line-height: 1.8;
}
</style>
