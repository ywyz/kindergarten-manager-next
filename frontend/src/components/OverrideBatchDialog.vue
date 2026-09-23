<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElButton,
  ElDatePicker,
  ElDialog,
  ElFormItem,
  ElMessage,
  ElOption,
  ElSelect,
} from 'element-plus'
import * as api from '../api'
import type { CalendarDay, ConfigurationChange, Term } from '../types'

const MAX_DATES = 366

const props = defineProps<{
  modelValue: boolean
  term: Term | null
  days: CalendarDay[]
  candidate?: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'preview-ready', change: ConfigurationChange): void
}>()

const selectedDates = ref<string[]>([])
const state = ref<'teaching' | 'non_teaching'>('teaching')
const reason = ref('')
const saving = ref(false)
const mode = ref<'set' | 'remove'>('set')
const stale = ref(false)
const latest = ref<{
  termVersion: number
  revisionId: string | null
  scheduleVersion: number
} | null>(null)

const dayByDate = computed(() => {
  const map = new Map<string, CalendarDay>()
  for (const d of props.days) map.set(d.date, d)
  return map
})

function resetFromCandidate(candidate: Record<string, unknown> | null | undefined) {
  if (!candidate) return false
  const dates = Array.isArray(candidate.dates) ? candidate.dates as Array<Record<string, unknown>> : []
  const dateStrings = dates.map((d) => String(d.date)).filter(Boolean)
  selectedDates.value = dateStrings
  if (dates.length && dates[0].state === null) {
    mode.value = 'remove'
  } else {
    mode.value = 'set'
    state.value = (dates[0]?.state as 'teaching' | 'non_teaching') || 'teaching'
    reason.value = (dates[0]?.reason as string) || ''
  }
  return true
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      if (!resetFromCandidate(props.candidate)) {
        selectedDates.value = []
        reason.value = ''
      }
      stale.value = false
      latest.value = null
    }
  },
)

async function loadLatestVersions() {
  const school = await api.getSchoolSettings()
  let termVersion: number
  let revisionId: string | null
  if (props.term) {
    const fresh = await api.getTerm(props.term.id)
    termVersion = fresh.version
    revisionId = fresh.calendar_revision_id
  } else {
    throw new Error('no term')
  }
  latest.value = { termVersion, revisionId, scheduleVersion: school.schedule_version }
}

async function buildPreview() {
  if (!props.term) {
    ElMessage.warning('请先选择一个学期')
    return
  }
  const dates = selectedDates.value || []
  if (!dates.length) {
    ElMessage.warning('请先选择日期')
    return
  }
  if (dates.length > MAX_DATES) {
    ElMessage.warning(`单次最多选择 ${MAX_DATES} 天`)
    return
  }

  // All selected dates must belong to the SAME term. Dates in the loaded
  // month are checked against their real term_id; dates outside the loaded
  // month are checked against the term's [start,end] bounds.
  const tStart = props.term.start_date
  const tEnd = props.term.end_date
  const outside = dates.filter((iso) => {
    const day = dayByDate.value.get(iso)
    if (day) return day.term_id !== props.term!.id
    return iso < tStart || iso > tEnd
  })
  if (outside.length) {
    ElMessage.warning(
      `有 ${outside.length} 个日期不在当前学期内（仅能批量处理同一学期日期），请先切换月份或学期`,
    )
    return
  }

  let payloadDates
  if (mode.value === 'set') {
    if (!reason.value.trim()) {
      ElMessage.warning('请填写统一的例外原因')
      return
    }
    payloadDates = dates.map((d) => ({
      date: d,
      state: state.value,
      reason: reason.value.trim(),
    }))
  } else {
    // Batch revoke selected exceptions.
    payloadDates = dates.map((d) => ({ date: d, state: null }))
  }

  saving.value = true
  try {
    if (!latest.value) await loadLatestVersions()
    const change = await api.createPreview({
      kind: 'calendar_override',
      target_id: props.term.id,
      dates: payloadDates,
      expected_term_version: latest.value!.termVersion,
      expected_calendar_revision_id: latest.value!.revisionId,
      expected_schedule_version: latest.value!.scheduleVersion,
    })
    emit('preview-ready', change)
    emit('update:modelValue', false)
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 409) {
      try {
        await loadLatestVersions()
      } catch {
        // keep stale state
      }
      stale.value = true
      ElMessage.warning('日历版本已变化，输入已保留，请核对后重新预览')
    } else {
      ElMessage.error(e.message || '生成例外预览失败')
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v) => emit('update:modelValue', v)"
    title="批量设置 / 撤销日期例外"
    width="500px"
    :close-on-click-modal="false"
  >
    <el-form-item label="处理方式">
      <el-select v-model="mode">
        <el-option label="批量设置为例外" value="set" />
        <el-option label="批量撤销例外" value="remove" />
      </el-select>
    </el-form-item>
    <el-form-item label="选择日期（可跨月多选）">
      <el-date-picker
        v-model="selectedDates"
        type="dates"
        value-format="YYYY-MM-DD"
        placeholder="点击选择多个日期"
      />
    </el-form-item>
    <p class="hint">
      已选 {{ selectedDates?.length || 0 }} 天，单次最多 {{ MAX_DATES }}
      天；所选日期必须都属于同一学期。
    </p>
    <template v-if="mode === 'set'">
      <el-form-item label="例外后有效状态">
        <el-select v-model="state">
          <el-option label="教学" value="teaching" />
          <el-option label="休息" value="non_teaching" />
        </el-select>
      </el-form-item>
      <el-form-item label="统一原因">
        <el-input
          v-model="reason"
          type="textarea"
          :rows="2"
          maxlength="200"
          show-word-limit
        />
      </el-form-item>
    </template>
    <p v-if="stale" class="stale">
      日历版本已变化，最新学期版本 {{ latest?.termVersion }}，请核对后重新预览（输入已保留）。
    </p>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="buildPreview">
        {{ stale ? '核对后重新预览' : '生成预览' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint { color: #909399; font-size: 0.85rem; }
.stale { color: #b88230; font-size: 0.875rem; margin-top: 6px; }
</style>
