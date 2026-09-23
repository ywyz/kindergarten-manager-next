<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElDivider,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
} from 'element-plus'
import type { ClassDetail, ClassInfo, ConfigurationChange } from '../types'
import * as api from '../api'
import { handleApiError } from '../auth'
import PreviewDialog from '../components/PreviewDialog.vue'
import {
  clearPending,
  getPending,
  rememberPending,
  restorePending,
} from '../composables/usePendingChange'

const classes = ref<ClassInfo[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const loading = ref(false)

const formVisible = ref(false)
const formKind = ref<'create' | 'update'>('create')
const form = ref({
  id: '',
  name: '',
  grade: 'small' as ClassInfo['grade'],
  headerNamesText: '',
  caregiverName: '',
  version: 1,
})
const submitting = ref(false)

const assignedTeachers = ref<Array<{ id: string; username: string; display_name: string | null }>>([])
const teachersLoading = ref(false)

const previewOpen = ref(false)
const stale = ref(false)
const staleMessage = ref('')

const pendingPreview = computed<ConfigurationChange | null>(() => {
  const p = getPending()
  if (p && p.kind.startsWith('class_')) return p
  return null
})

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const page = ref(1)

async function load() {
  loading.value = true
  try {
    const res = await api.listClasses({ offset: offset.value, limit: limit.value })
    classes.value = res.items
    total.value = res.total
    limit.value = res.limit
    page.value = Math.floor(offset.value / limit.value) + 1
  } catch (err) {
    handleApiError(err, '加载班级列表失败')
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  offset.value = (p - 1) * limit.value
  load()
}

function openCreate() {
  stale.value = false
  staleMessage.value = ''
  formKind.value = 'create'
  form.value = {
    id: '',
    name: '',
    grade: 'small',
    headerNamesText: '',
    caregiverName: '',
    version: 1,
  }
  assignedTeachers.value = []
  formVisible.value = true
}

async function openEdit(row: ClassInfo) {
  stale.value = false
  staleMessage.value = ''
  formKind.value = 'update'
  form.value = {
    id: row.id,
    name: row.name,
    grade: row.grade,
    headerNamesText: row.header_teacher_names.join('\n'),
    caregiverName: row.caregiver_name || '',
    version: row.version,
  }
  assignedTeachers.value = []
  formVisible.value = true
  teachersLoading.value = true
  try {
    const detail = await api.getClass(row.id)
    assignedTeachers.value = detail.assigned_teachers
  } catch (err) {
    handleApiError(err, '加载班级真实成员失败')
  } finally {
    teachersLoading.value = false
  }
}

function parseHeaderNames(): string[] {
  // One name per line (or separated by Chinese/commas). Blank lines dropped.
  return form.value.headerNamesText
    .split(/[\n,，、;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function loadLatestClassVersion() {
  if (formKind.value !== 'update' || !form.value.id) return form.value.version
  const detail = await api.getClass(form.value.id)
  assignedTeachers.value = detail.assigned_teachers
  form.value.version = detail.version
  return detail.version
}

async function submit() {
  const headerNames = parseHeaderNames()
  if (headerNames.length > 20) {
    ElMessage.warning('表头教师名单最多 20 项')
    return
  }
  submitting.value = true
  try {
    let payload: Record<string, unknown>
    if (formKind.value === 'create') {
      payload = {
        kind: 'class_create',
        name: form.value.name,
        grade: form.value.grade,
        header_teacher_names: headerNames,
        caregiver_name: form.value.caregiverName.trim() || null,
      }
    } else {
      const latestVersion = await loadLatestClassVersion()
      payload = {
        kind: 'class_update',
        target_id: form.value.id,
        name: form.value.name,
        grade: form.value.grade,
        header_teacher_names: headerNames,
        caregiver_name: form.value.caregiverName.trim() || null,
        expected_version: latestVersion,
      }
    }
    const change = await api.createPreview(payload)
    rememberPending(change)
    previewOpen.value = true
    stale.value = false
    staleMessage.value = ''
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'NO_CHANGES') {
      ElMessage.info('内容没有变更')
      return
    }
    if (e.code === 'VERSION_CONFLICT' || e.code === 'CLASS_NAME_TAKEN') {
      stale.value = true
      staleMessage.value = e.message
      return
    }
    handleApiError(err, '保存失败')
  } finally {
    submitting.value = false
  }
}

function restoreFormFromCandidate(change: ConfigurationChange) {
  const c = change.candidate
  if (!c) return
  if (change.kind === 'class_create') {
    formKind.value = 'create'
    form.value.id = ''
    form.value.version = 1
  } else if (change.kind === 'class_update') {
    formKind.value = 'update'
    form.value.id = (c.target_id as string) || ''
    form.value.version =
      typeof c.expected_version === 'number' ? c.expected_version : 1
  }
  form.value.name = (c.name as string) || ''
  form.value.grade = (c.grade as ClassInfo['grade']) || 'small'
  const headers = Array.isArray(c.header_teacher_names)
    ? (c.header_teacher_names as string[])
    : []
  form.value.headerNamesText = headers.join('\n')
  form.value.caregiverName = (c.caregiver_name as string) || ''
}

async function init() {
  try {
    const outcome = await restorePending()
    if (outcome?.outcome === 'recovered' && outcome.change.kind.startsWith('class_')) {
      restoreFormFromCandidate(outcome.change)
      previewOpen.value = true
      // Background refresh of assigned teachers for updates so the read-only
      // detail stays current, but do not overwrite the candidate form values.
      if (formKind.value === 'update' && form.value.id) {
        api.getClass(form.value.id)
          .then((detail) => { assignedTeachers.value = detail.assigned_teachers })
          .catch(() => { /* detail is secondary on recovery */ })
      }
      return
    }
  } catch (err) {
    handleApiError(err, '恢复待处理预览失败')
  }
  await load()
}

async function onApplied() {
  previewOpen.value = false
  clearPending()
  formVisible.value = false
  await load()
}

async function onStale() {
  previewOpen.value = false
  stale.value = true
  staleMessage.value = '数据版本已变化；班级表单已保留，请核对后重新预览'
  // Refresh the list so the latest server state is visible, but keep the
  // dialog form values intact.
  await load()
}

function onRePreview() {
  previewOpen.value = false
  formVisible.value = true
  submit()
}

function onFormClosed() {
  // Closing the form without applying does not clear the pending pointer;
  // the recovered candidate can still be re-opened via re-preview.
}

onMounted(init)
</script>

<template>
  <el-card>
    <div class="toolbar">
      <h3>班级管理</h3>
      <el-button type="primary" @click="openCreate">新建班级</el-button>
    </div>

    <el-table :data="classes" v-loading="loading" style="width: 100%">
      <el-table-column prop="name" label="班级名称" />
      <el-table-column label="年级">
        <template #default="{ row }">{{ GRADE_LABELS[row.grade] }}</template>
      </el-table-column>
      <el-table-column label="表头教师">
        <template #default="{ row }">
          {{ row.header_teacher_names.length ? row.header_teacher_names.join('、') : '（未填写）' }}
        </template>
      </el-table-column>
      <el-table-column label="保育员">
        <template #default="{ row }">{{ row.caregiver_name || '（未填写）' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row as ClassInfo)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      :page-size="limit"
      :total="total"
      layout="prev, pager, next"
      @current-change="onPageChange"
    />
  </el-card>

  <el-dialog
    v-model="formVisible"
    :title="formKind === 'create' ? '新建班级' : '编辑班级'"
    width="520px"
    @update:model-value="(v) => { if (!v) onFormClosed() }"
  >
    <el-form label-position="top">
      <el-form-item label="班级名称（全园唯一）">
        <el-input v-model="form.name" maxlength="80" show-word-limit />
      </el-form-item>
      <el-form-item label="年级">
        <el-select v-model="form.grade">
          <el-option label="小班" value="small" />
          <el-option label="中班" value="middle" />
          <el-option label="大班" value="large" />
        </el-select>
      </el-form-item>
      <el-form-item label="表头教师名单（每行一个姓名，不会随账号自动同步）">
        <el-input
          v-model="form.headerNamesText"
          type="textarea"
          :rows="4"
          placeholder="未填写"
        />
      </el-form-item>
      <el-form-item label="保育员姓名">
        <el-input v-model="form.caregiverName" maxlength="80" placeholder="未填写" />
      </el-form-item>
      <template v-if="formKind === 'update'">
        <el-divider />
        <el-form-item label="实际账号归属（只读，与表头名单独立）">
          <el-table
            :data="assignedTeachers"
            v-loading="teachersLoading"
            size="small"
            style="width: 100%"
            empty-text="暂无分配教师"
          >
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="姓名">
              <template #default="{ row }">
                {{ row.display_name || '（未填写）' }}
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
      </template>
    </el-form>
    <div v-if="stale" class="stale">
      <p>{{ staleMessage }}</p>
    </div>
    <template #footer>
      <el-button @click="formVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ stale ? '核对后重新预览' : '下一步：预览' }}
      </el-button>
    </template>
  </el-dialog>

  <PreviewDialog
    v-model="previewOpen"
    :change="pendingPreview"
    @applied="onApplied"
    @stale="onStale"
    @re-preview="onRePreview"
  />
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.stale {
  margin-top: 10px;
  padding: 8px 12px;
  background: #fdf6ec;
  border-radius: 4px;
  color: #b88230;
  font-size: 0.875rem;
}
</style>
