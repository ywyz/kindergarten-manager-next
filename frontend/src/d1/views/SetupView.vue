<script setup lang="ts">
/**
 * First setup: one local teacher profile (name, class name+grade, term
 * name+dates, optional school). The initialization request id is a UUID kept
 * for the lifetime of this form so an unclear result is retried with the
 * same key (the server then reads the committed profile back).
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError } from '../client'
import type { LocalContext } from '../types'

defineProps<{ context: LocalContext | null }>()
const emit = defineEmits<{
  (e: 'initialized', context: LocalContext): void
  (e: 'open-maintenance'): void
}>()

const form = ref({
  display_name: '',
  class_name: '',
  grade: 'middle' as 'small' | 'middle' | 'large',
  term_name: '',
  range: [] as string[],
  school_name: '',
})
const submitting = ref(false)
const errorText = ref('')
// One request id per attempt sequence: kept across retries after unclear
// results, so the server can return the original objects (never rebuilt).
let requestId = crypto.randomUUID()

function validate(): string {
  const value = form.value
  if (!value.display_name.trim()) return '请填写姓名'
  if (!value.class_name.trim()) return '请填写班级名称'
  if (!value.term_name.trim()) return '请填写学期名称'
  if (!value.range || value.range.length !== 2) return '请选择学期起止日期'
  return ''
}

interface SetupFill {
  display_name: string
  class_name: string
  grade: 'small' | 'middle' | 'large'
  term_name: string
  start_date: string
  end_date: string
  school_name?: string | null
}

onMounted(() => {
  // Verification hook for the packaged selftest driver: fills the same form
  // model and submits through the real submit() path.
  ;(window as unknown as { __d1Setup?: object }).__d1Setup = {
    fill: (fields: SetupFill) => {
      form.value = {
        display_name: fields.display_name,
        class_name: fields.class_name,
        grade: fields.grade,
        term_name: fields.term_name,
        range: [fields.start_date, fields.end_date],
        school_name: fields.school_name ?? '',
      }
    },
    submit: () => submit(),
  }
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Setup?: object }).__d1Setup
})

async function submit(): Promise<void> {
  if (submitting.value) return
  const problem = validate()
  if (problem) {
    errorText.value = problem
    return
  }
  submitting.value = true
  errorText.value = ''
  try {
    const payload = await apiPost<LocalContext>('/api/local/initialize', {
      request_id: requestId,
      display_name: form.value.display_name,
      class_name: form.value.class_name,
      grade: form.value.grade,
      term_name: form.value.term_name,
      start_date: form.value.range[0],
      end_date: form.value.range[1],
      school_name: form.value.school_name.trim() || null,
    })
    emit('initialized', payload)
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 'ALREADY_INITIALIZED') {
        // Another process completed the setup: read it back, never overwrite.
        ElMessage.info('本地档案已初始化，正在读取现有资料')
        try {
          const existing = await apiGet<LocalContext>('/api/local/context')
          emit('initialized', existing)
          return
        } catch {
          // fall through to the message below
        }
      }
      errorText.value = err.message
      if (err.code === 'ALREADY_INITIALIZED' || err.code === 'INITIALIZATION_REQUEST_CONFLICT') {
        // A retry with this key can no longer create; a fresh key is needed.
        requestId = crypto.randomUUID()
      }
    } else {
      // Transport-level: the result may be unknown; keep the same key for retry.
      errorText.value = `初始化结果未知：${String(err)}。可重试，应用会复用同一请求 ID。`
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="setup" data-d1="setup">
    <el-card shadow="never">
      <template #header><span>首次设置（一个本地教师档案）</span></template>
      <p class="muted">
        资料仅保存在本机。填写后将直接进入工作台；园所名称可留空后补。
        也可先从本地备份恢复，无需先填写临时档案。
      </p>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="姓名" required>
          <el-input v-model="form.display_name" maxlength="80" data-d1="display-name" />
        </el-form-item>
        <el-form-item label="班级名称" required>
          <el-input v-model="form.class_name" maxlength="80" data-d1="class-name" />
        </el-form-item>
        <el-form-item label="年级" required>
          <el-select v-model="form.grade" data-d1="grade">
            <el-option label="小班" value="small" />
            <el-option label="中班" value="middle" />
            <el-option label="大班" value="large" />
          </el-select>
        </el-form-item>
        <el-form-item label="学期名称" required>
          <el-input v-model="form.term_name" maxlength="80" data-d1="term-name" />
        </el-form-item>
        <el-form-item label="学期日期" required>
          <el-date-picker
            v-model="form.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            data-d1="term-range"
          />
        </el-form-item>
        <el-form-item label="园所名称">
          <el-input
            v-model="form.school_name"
            maxlength="120"
            placeholder="可留空"
            data-d1="school-name"
          />
        </el-form-item>
      </el-form>
      <el-alert v-if="errorText" type="error" :closable="false" :title="errorText" data-d1="setup-error" />
      <div class="actions">
        <el-button type="primary" :loading="submitting" data-d1="initialize" @click="submit">
          完成设置并进入工作台
        </el-button>
        <el-button data-d1="setup-restore" @click="emit('open-maintenance')">
          从本地备份恢复
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.setup {
  max-width: 640px;
  margin: 40px auto 0;
}
.actions {
  margin-top: 16px;
}
</style>
