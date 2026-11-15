<script setup lang="ts">
/**
 * First setup: one local teacher profile (name, grade + class number 1-6,
 * term name+dates, optional school). The initialization request id is a UUID
 * kept for the lifetime of this form so an unclear result is retried with the
 * same key (the server then reads the committed profile back).
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError } from '../client'
import type { LocalContext } from '../types'

type Grade = 'small' | 'middle' | 'large'
const GRADE_PREFIX: Record<Grade, string> = {
  small: '小',
  middle: '中',
  large: '大',
}
const CLASS_NUMBER_LABELS = ['一', '二', '三', '四', '五', '六']

defineProps<{ context: LocalContext | null }>()
const emit = defineEmits<{
  (e: 'initialized', context: LocalContext): void
  (e: 'open-maintenance'): void
}>()

const form = ref({
  display_name: '',
  grade: 'middle' as Grade,
  class_number: null as number | null,
  term_name: '',
  range: [] as string[],
  school_name: '',
})
const submitting = ref(false)
const errorText = ref('')
const derivedClassName = computed(() => {
  const number = form.value.class_number
  if (number === null || !Number.isInteger(number) || number < 1 || number > 6) {
    return ''
  }
  return `${GRADE_PREFIX[form.value.grade]}${CLASS_NUMBER_LABELS[number - 1]}班`
})

const editorOpen = ref<'identity' | 'term' | null>(null)
const editorBaseline = ref('')
const editorError = ref('')
const editorComposing = ref(false)
const editName = ref('')
const editGrade = ref<Grade>('middle')
const editClassNumber = ref<number | null>(null)
const editSchool = ref('')
const editTermName = ref('')
const editTermRange = ref<string[]>([])

function classNameFor(grade: Grade, number: number | null): string {
  if (number === null || !Number.isInteger(number) || number < 1 || number > 6) {
    return ''
  }
  return `${GRADE_PREFIX[grade]}${CLASS_NUMBER_LABELS[number - 1]}班`
}

const editDerivedClassName = computed(() =>
  classNameFor(editGrade.value, editClassNumber.value),
)

function editorCopySnapshot(): string {
  if (editorOpen.value === 'identity') {
    return JSON.stringify({
      name: editName.value,
      grade: editGrade.value,
      number: editClassNumber.value,
      school: editSchool.value,
    })
  }
  return JSON.stringify({
    term: editTermName.value,
    range: [...editTermRange.value],
  })
}

const editorDirty = computed(
  () =>
    editorOpen.value !== null
    && (editorCopySnapshot() !== editorBaseline.value || editorComposing.value),
)
function openIdentityEditor(): void {
  editorOpen.value = 'identity'
  editName.value = form.value.display_name
  editGrade.value = form.value.grade
  editClassNumber.value = form.value.class_number
  editSchool.value = form.value.school_name
  editorBaseline.value = editorCopySnapshot()
  editorError.value = ''
}

function openTermEditor(): void {
  editorOpen.value = 'term'
  editTermName.value = form.value.term_name
  editTermRange.value = [...form.value.range]
  editorBaseline.value = editorCopySnapshot()
  editorError.value = ''
}

function closeEditor(): void {
  editorOpen.value = null
  editorComposing.value = false
  editorBaseline.value = ''
  editorError.value = ''
}

function onEditorDialog(value: boolean): void {
  if (!value) closeEditor()
}

function confirmEditor(): void {
  if (!editorOpen.value) return
  if (submitting.value) {
    editorError.value = '正在提交首次设置：请等待结果后再填回草稿'
    return
  }
  if (editorOpen.value === 'identity') {
    form.value.display_name = editName.value
    form.value.grade = editGrade.value
    form.value.class_number = editClassNumber.value
    form.value.school_name = editSchool.value
  } else {
    form.value.term_name = editTermName.value
    form.value.range = [...editTermRange.value]
  }
  closeEditor()
  errorText.value = ''
  ElMessage.info('已填回设置草稿；请核对后完成设置')
}

// One request id per attempt sequence: kept across retries after unclear
// results, so the server can return the original objects (never rebuilt).
let requestId = crypto.randomUUID()

function validate(): string {
  const value = form.value
  if (!value.display_name.trim()) return '请填写姓名'
  if (
    value.class_number === null ||
    !Number.isInteger(value.class_number) ||
    value.class_number < 1 ||
    value.class_number > 6
  ) {
    return '请选择班级序号（1–6）'
  }
  if (!value.term_name.trim()) return '请填写学期名称'
  if (!value.range || value.range.length !== 2) return '请选择学期起止日期'
  return ''
}

interface SetupFill {
  display_name: string
  grade: Grade
  class_number: number
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
        grade: fields.grade,
        class_number: fields.class_number,
        term_name: fields.term_name,
        range: [fields.start_date, fields.end_date],
        school_name: fields.school_name ?? '',
      }
      closeEditor()
    },
    submit: () => submit(),
  }
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Setup?: object }).__d1Setup
})

async function submit(): Promise<void> {
  if (submitting.value) return
  if (editorOpen.value && editorDirty.value) {
    errorText.value = '编辑弹窗尚未填回草稿：请先填回或取消编辑'
    return
  }
  if (editorOpen.value) closeEditor()
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
      class_name: derivedClassName.value,
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
      <el-alert v-if="errorText" type="error" :closable="false" :title="errorText" data-d1="setup-error" />
      <div class="kgm-page-layout">
        <div class="kgm-page-main">
          <div class="kgm-sheet" data-d1="setup-summary">
            <div class="kgm-sheet-header">首次设置</div>
            <div class="kgm-sheet-row">
              <div class="kgm-sheet-label">教师与班级</div>
              <div class="kgm-sheet-value" data-d1="setup-identity-summary">
                <div>姓名：{{ form.display_name || '（未填写）' }}</div>
                <div>园所名称：{{ form.school_name || '（可留空）' }}</div>
                <div>年级：{{ { small: '小班', middle: '中班', large: '大班' }[form.grade] }}</div>
                <div>班级：{{ derivedClassName || '（未选择班号）' }}</div>
              </div>
              <div class="kgm-sheet-actions">
                <el-button size="small" data-d1="setup-edit-identity" @click="openIdentityEditor">
                  编辑
                </el-button>
              </div>
            </div>
            <div class="kgm-sheet-row">
              <div class="kgm-sheet-label">学期</div>
              <div class="kgm-sheet-value" data-d1="setup-term-summary">
                <div>学期名称：{{ form.term_name || '（未填写）' }}</div>
                <div>起始日期：{{ form.range[0] || '（未选择）' }}</div>
                <div>结束日期：{{ form.range[1] || '（未选择）' }}</div>
              </div>
              <div class="kgm-sheet-actions">
                <el-button size="small" data-d1="setup-edit-term" @click="openTermEditor">
                  编辑
                </el-button>
              </div>
            </div>
          </div>
        </div>
        <aside class="kgm-page-rail" aria-label="首次设置操作">
          <div class="kgm-rail-panel">
            <h3 class="kgm-rail-title">操作</h3>
            <el-button
              type="primary"
              class="kgm-primary-action"
              :loading="submitting"
              data-d1="initialize"
              @click="submit"
            >
              完成设置并进入工作台
            </el-button>
            <el-button data-d1="setup-restore" :disabled="editorDirty" @click="emit('open-maintenance')">
              从本地备份恢复
            </el-button>
            <p class="muted">姓名、年级、班号和学期为必填；园所可留空。所有资料只保存在本机。</p>
          </div>
        </aside>
      </div>
    </el-card>

    <el-dialog
      :model-value="editorOpen === 'identity'"
      title="编辑姓名与班级"
      width="540px"
      :close-on-click-modal="false"
      data-d1="setup-editor-identity"
      @compositionstart="editorComposing = true"
      @compositionend="editorComposing = false"
      @update:model-value="onEditorDialog"
    >
      <p class="muted">这里先编辑这组设置；填回后仍由页面底部“完成设置”提交。</p>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="姓名" required>
          <el-input v-model="editName" maxlength="80" data-d1="display-name" />
        </el-form-item>
        <el-form-item label="年级" required>
          <el-select v-model="editGrade" data-d1="grade">
            <el-option label="小班" value="small" />
            <el-option label="中班" value="middle" />
            <el-option label="大班" value="large" />
          </el-select>
        </el-form-item>
        <el-form-item label="班级" required>
          <div class="class-picker">
            <el-select
              v-model="editClassNumber"
              placeholder="选择班号"
              data-d1="class-number"
            >
              <el-option
                v-for="(label, index) in CLASS_NUMBER_LABELS"
                :key="index + 1"
                :label="`${label}班`"
                :value="index + 1"
              />
            </el-select>
            <span class="class-preview" aria-live="polite" data-d1="class-name-preview">
              {{ editDerivedClassName || '请选择班号' }}
            </span>
          </div>
        </el-form-item>
        <el-form-item label="园所名称">
          <el-input
            v-model="editSchool"
            maxlength="120"
            placeholder="可留空"
            data-d1="school-name"
          />
        </el-form-item>
      </el-form>
      <el-alert v-if="editorError" type="error" :closable="false" :title="editorError" data-d1="setup-editor-error" />
      <template #footer>
        <div class="kgm-dialog-footer">
          <el-button data-d1="setup-editor-cancel" @click="closeEditor">取消</el-button>
          <el-button type="primary" data-d1="setup-editor-apply" :disabled="submitting" @click="confirmEditor">填回草稿</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="editorOpen === 'term'"
      title="编辑学期"
      width="540px"
      :close-on-click-modal="false"
      data-d1="setup-editor-term"
      @compositionstart="editorComposing = true"
      @compositionend="editorComposing = false"
      @update:model-value="onEditorDialog"
    >
      <p class="muted">学期名称和起止日期先填回草稿，再由页面底部“完成设置”提交。</p>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="学期名称" required>
          <el-input v-model="editTermName" maxlength="80" data-d1="term-name" />
        </el-form-item>
        <el-form-item label="学期日期" required>
          <el-date-picker
            v-model="editTermRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            data-d1="term-range"
          />
        </el-form-item>
      </el-form>
      <el-alert v-if="editorError" type="error" :closable="false" :title="editorError" data-d1="setup-editor-error" />
      <template #footer>
        <div class="kgm-dialog-footer">
          <el-button data-d1="setup-editor-cancel" @click="closeEditor">取消</el-button>
          <el-button type="primary" data-d1="setup-editor-apply" :disabled="submitting" @click="confirmEditor">填回草稿</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.setup {
  max-width: none;
  margin: 0;
}
.setup :deep(.el-card) {
  border-radius: var(--kgm-radius);
}
.kgm-page-layout {
  margin-top: 16px;
}
.class-picker {
  display: flex;
  align-items: center;
  gap: 8px 12px;
  flex-wrap: wrap;
  min-width: 0;
}
.class-picker :deep(.el-select) {
  flex: 1 1 132px;
  min-width: 112px;
}
.class-preview {
  flex: 1 1 120px;
  min-width: 0;
  color: var(--kgm-text);
  overflow-wrap: anywhere;
}
@media (max-width: 640px) {
  .setup {
    margin: 16px 12px 0;
  }
  .setup :deep(.el-form-item__label) {
    width: 72px !important;
  }
}
</style>
