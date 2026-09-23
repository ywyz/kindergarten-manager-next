<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  ElButton,
  ElDatePicker,
  ElDialog,
  ElFormItem,
  ElInput,
  ElMessage,
} from 'element-plus'
import * as api from '../api'
import type { ConfigurationChange, Term } from '../types'

const props = defineProps<{
  modelValue: boolean
  editing: Term | null
  candidate?: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'preview-ready', change: ConfigurationChange): void
}>()

const name = ref('')
const range = ref<[string, string] | []>([])
const saving = ref(false)
const stale = ref(false)
const staleMessage = ref('')
// Latest authoritative versions loaded separately on conflict; the form
// values are preserved, never silently overwritten.
const latest = ref<{
  termVersion: number | null
  scheduleVersion: number
} | null>(null)

function resetFromCandidate(candidate: Record<string, unknown> | null | undefined) {
  if (!candidate) return false
  if (typeof candidate.name === 'string') name.value = candidate.name
  if (
    typeof candidate.start_date === 'string' &&
    typeof candidate.end_date === 'string'
  ) {
    range.value = [candidate.start_date, candidate.end_date]
  }
  return true
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      stale.value = false
      staleMessage.value = ''
      latest.value = null
      if (!resetFromCandidate(props.candidate)) {
        if (props.editing) {
          name.value = props.editing.name
          range.value = [props.editing.start_date, props.editing.end_date]
        } else {
          name.value = ''
          range.value = []
        }
      }
    }
  },
)

async function loadLatestVersions() {
  const school = await api.getSchoolSettings()
  let termVersion: number | null = null
  if (props.editing) {
    const fresh = await api.getTerm(props.editing.id)
    termVersion = fresh.version
  }
  latest.value = { termVersion, scheduleVersion: school.schedule_version }
}

async function buildPreview() {
  if (!name.value.trim()) {
    ElMessage.warning('请填写学期名称')
    return
  }
  if (!Array.isArray(range.value) || range.value.length !== 2) {
    ElMessage.warning('请选择完整的起止日期')
    return
  }
  saving.value = true
  try {
    if (!latest.value) await loadLatestVersions()
    const scheduleVersion = latest.value!.scheduleVersion
    let change: ConfigurationChange
    const base = {
      name: name.value.trim(),
      start_date: range.value[0],
      end_date: range.value[1],
      expected_schedule_version: scheduleVersion,
    }
    if (props.editing) {
      change = await api.createPreview({
        kind: 'term_update',
        target_id: props.editing.id,
        ...base,
        expected_version: latest.value!.termVersion,
      })
    } else {
      change = await api.createPreview({ kind: 'term_create', ...base })
    }
    emit('preview-ready', change)
    emit('update:modelValue', false)
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 409) {
      // Keep the form and the stale context; just refresh versions, then let
      // the teacher explicitly re-preview. No silent overwrite, no closing.
      try {
        await loadLatestVersions()
      } catch {
        // Keep showing the stale state even if the refresh fails.
      }
      stale.value = true
      staleMessage.value =
        e.code === 'PREVIEW_EXPIRED'
          ? '预览已过期，可在核对最新版本后重新预览'
          : '数据版本已变化；下方为最新版本，输入已保留，请核对后重新预览'
    } else {
      ElMessage.error(e.message || '生成学期预览失败')
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
    :title="editing ? '编辑学期' : '新建学期'"
    width="460px"
    :close-on-click-modal="false"
  >
    <el-form-item label="学期名称">
      <el-input v-model="name" placeholder="如：2026 年秋季学期" />
    </el-form-item>
    <el-form-item label="起止日期">
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
      />
    </el-form-item>
    <p class="hint">学期闭区间不可与其他学期相交（含端点）。</p>

    <div v-if="stale" class="stale">
      <p>{{ staleMessage }}</p>
      <p v-if="latest" class="versions">
        最新 schedule 版本：{{ latest.scheduleVersion }}<template
          v-if="latest.termVersion !== null">，学期版本：{{ latest.termVersion }}</template>
      </p>
    </div>

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
.stale {
  margin-top: 10px;
  padding: 8px 12px;
  background: #fdf6ec;
  border-radius: 4px;
  color: #b88230;
  font-size: 0.875rem;
}
.versions { margin: 4px 0 0; }
</style>
