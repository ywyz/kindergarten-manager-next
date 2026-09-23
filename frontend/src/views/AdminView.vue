<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElInput,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
} from 'element-plus'
import type { ClassInfo, TeacherListItem } from '../types'
import { doLogout, handleApiError } from '../auth'
import * as api from '../api'
import ClassesView from './ClassesView.vue'
import SchoolProfileView from './SchoolProfileView.vue'
import TermCalendarView from './TermCalendarView.vue'
import AdminDailyPlansView from './AdminDailyPlansView.vue'
import { restorePending } from '../composables/usePendingChange'

const emit = defineEmits<{
  (e: 'go-settings'): void
  (e: 'logged-out'): void
}>()

const activeTab = ref('teachers')

// -------------------------------------------------------------------------
// Teachers tab
// -------------------------------------------------------------------------

const teachers = ref<TeacherListItem[]>([])
const allClasses = ref<ClassInfo[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const query = ref('')
const statusFilter = ref<'' | 'assigned' | 'pending_assignment'>('')
const loading = ref(false)

const resetDialogVisible = ref(false)
const resetTarget = ref<TeacherListItem | null>(null)
const newPassword = ref('')
const newPasswordConfirm = ref('')
const resetting = ref(false)

// Assignment dialog
const assignDialogVisible = ref(false)
const assignTarget = ref<TeacherListItem | null>(null)
const assignClasses = ref<ClassInfo[]>([])
const assignClassTotal = ref(0)
const assignClassOffset = ref(0)
const assignClassLimit = ref(10)
const selectedClassId = ref('')
const selectedClass = ref<ClassInfo | null>(null)
const assignClassLoading = ref(false)
const assigning = ref(false)

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const page = computed({
  get: () => Math.floor(offset.value / limit.value) + 1,
  set: (p) => { offset.value = (p - 1) * limit.value },
})

function clearResetForm() {
  resetTarget.value = null
  newPassword.value = ''
  newPasswordConfirm.value = ''
}

function className(id: string): string {
  return allClasses.value.find((c) => c.id === id)?.name || id
}

async function load() {
  loading.value = true
  try {
    if (allClasses.value.length === 0) {
      const classRes = await api.listClasses({ offset: 0, limit: 100 })
      allClasses.value = classRes.items
    }
    const res = await api.listTeachers({
      offset: offset.value,
      limit: limit.value,
      q: query.value || undefined,
      assignment_status: statusFilter.value || undefined,
    })
    teachers.value = res.items
    total.value = res.total
    limit.value = res.limit
    if (resetDialogVisible.value && resetTarget.value && !teachers.value.some(t => t.id === resetTarget.value!.id)) {
      resetDialogVisible.value = false
      clearResetForm()
      ElMessage.warning('目标账号已不可见，请重新搜索后操作')
    }
  } catch (err) {
    handleApiError(err, '加载教师列表失败')
  } finally {
    loading.value = false
  }
}

function openReset(row: TeacherListItem) {
  resetTarget.value = row
  newPassword.value = ''
  newPasswordConfirm.value = ''
  resetDialogVisible.value = true
}

const assignClassPage = computed({
  get: () => Math.floor(assignClassOffset.value / assignClassLimit.value) + 1,
  set: (p) => { assignClassOffset.value = (p - 1) * assignClassLimit.value },
})

async function loadAssignClasses() {
  assignClassLoading.value = true
  try {
    const res = await api.listClasses({
      offset: assignClassOffset.value,
      limit: assignClassLimit.value,
    })
    assignClasses.value = res.items
    assignClassTotal.value = res.total
    assignClassLimit.value = res.limit
    if (selectedClassId.value && !assignClasses.value.some(c => c.id === selectedClassId.value)) {
      selectedClassId.value = ''
      selectedClass.value = null
    }
    if (res.total === 0) {
      ElMessage.warning('请先在“班级管理”中创建班级')
    }
  } catch (err) {
    handleApiError(err, '加载班级列表失败')
  } finally {
    assignClassLoading.value = false
  }
}

async function openAssign(row: TeacherListItem) {
  assignTarget.value = row
  selectedClassId.value = ''
  selectedClass.value = null
  assignClassOffset.value = 0
  assignDialogVisible.value = true
  await loadAssignClasses()
}

watch(selectedClassId, (id) => {
  selectedClass.value = assignClasses.value.find((c) => c.id === id) || null
})

function onAssignClassPageChange(p: number) {
  assignClassPage.value = p
  loadAssignClasses()
}

async function confirmAssign() {
  if (!assignTarget.value || !selectedClass.value) return
  assigning.value = true
  const target = assignTarget.value
  const targetClass = selectedClass.value
  try {
    await api.assignTeacher(target.id, {
      class_id: targetClass.id,
      expected_version: target.version,
      expected_class_version: targetClass.version,
    })
    ElMessage.success('分配成功')
    assignDialogVisible.value = false
    await load()
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'VERSION_CONFLICT' || e.code === 'ALREADY_ASSIGNED') {
      ElMessage.warning(e.message)
      assignDialogVisible.value = false
      await load()
      return
    }
    handleApiError(err, '分配失败')
  } finally {
    assigning.value = false
  }
}

watch(resetDialogVisible, (visible) => {
  if (!visible) clearResetForm()
})

onBeforeUnmount(clearResetForm)

async function confirmReset() {
  if (!resetTarget.value) return
  if (newPassword.value !== newPasswordConfirm.value) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  resetting.value = true
  const targetId = resetTarget.value.id
  try {
    await api.resetTeacherPassword(targetId, {
      new_password: newPassword.value,
      expected_version: resetTarget.value.version,
    })
    ElMessage.success('密码已重置，该账号现有登录将失效')
    resetDialogVisible.value = false
    clearResetForm()
    await load()
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'VERSION_CONFLICT') {
      newPassword.value = ''
      newPasswordConfirm.value = ''
      await load()
      const latest = teachers.value.find(t => t.id === targetId)
      if (latest) {
        resetTarget.value = latest
        ElMessage.warning('账号信息已变化，请确认目标后重新提交')
      } else {
        resetDialogVisible.value = false
        clearResetForm()
        ElMessage.warning('目标账号已不可见，请重新搜索后操作')
      }
      return
    }
    handleApiError(err, '重置密码失败')
  } finally {
    resetting.value = false
  }
}

async function logout() {
  try {
    await doLogout()
    emit('logged-out')
  } catch (err) {
    handleApiError(err, '退出失败')
  }
}

async function restorePreviewState() {
  try {
    const result = await restorePending()
    if (!result) return
    if (result.outcome === 'already_applied') {
      ElMessage.success('检测到上次变更已生效')
      return
    }
    if (result.outcome === 'recovered') {
      const kind = result.change.kind
      if (kind.startsWith('class_')) {
        activeTab.value = 'classes'
      } else if (kind === 'school_update') {
        activeTab.value = 'school'
      } else if (kind.startsWith('term_') || kind.startsWith('calendar_')) {
        activeTab.value = 'calendar'
      }
      ElMessage.info('已恢复未完成的预览，请核对后确认')
    }
  } catch (err) {
    handleApiError(err, '恢复未完成预览失败（可稍后重试）')
  }
}

onMounted(async () => {
  await load()
  await restorePreviewState()
})
</script>

<template>
  <div class="admin">
    <div class="toolbar">
      <h2>幼儿园管理</h2>
      <div class="actions">
        <el-button @click="$emit('go-settings')">系统设置</el-button>
        <el-button @click="logout">退出</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="教师账号" name="teachers">
        <el-card>
          <div class="search">
            <el-input v-model="query" placeholder="搜索用户名或姓名" clearable @change="offset = 0; load()" />
            <el-select v-model="statusFilter" placeholder="分配状态" clearable @change="offset = 0; load()">
              <el-option label="待分配" value="pending_assignment" />
              <el-option label="已分配" value="assigned" />
            </el-select>
            <el-button type="primary" @click="offset = 0; load()">搜索</el-button>
          </div>
          <el-table :data="teachers" v-loading="loading" style="width: 100%">
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="姓名">
              <template #default="{ row }">
                {{ row.display_name || '（未填写）' }}
              </template>
            </el-table-column>
            <el-table-column label="分配状态">
              <template #default="{ row }">
                {{ row.assignment_status === 'assigned' ? '已分配' : '待分配' }}
              </template>
            </el-table-column>
            <el-table-column label="所属班级">
              <template #default="{ row }">
                {{ row.class_id ? className(row.class_id as string) : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button
                  v-if="row.assignment_status !== 'assigned'"
                  size="small"
                  type="primary"
                  @click="openAssign(row as TeacherListItem)"
                >
                  分配班级
                </el-button>
                <el-button size="small" @click="openReset(row as TeacherListItem)">重置密码</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="page"
            :page-size="limit"
            :total="total"
            layout="prev, pager, next"
            @current-change="load"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="班级管理" name="classes">
        <ClassesView />
      </el-tab-pane>

      <el-tab-pane label="园所资料" name="school">
        <SchoolProfileView />
      </el-tab-pane>

      <el-tab-pane label="学期与日历" name="calendar">
        <TermCalendarView />
      </el-tab-pane>

      <el-tab-pane label="日计划" name="plans">
        <AdminDailyPlansView />
      </el-tab-pane>
    </el-tabs>

    <!-- First assignment dialog -->
    <el-dialog v-model="assignDialogVisible" title="首次分配班级" width="560px">
      <p>教师用户名：<strong>{{ assignTarget?.username }}</strong></p>
      <p>姓名：{{ assignTarget?.display_name || '（未填写，不阻止分配）' }}</p>
      <div class="assign-field">
        <label>目标班级（分页选择）</label>
        <el-table
          :data="assignClasses"
          v-loading="assignClassLoading"
          size="small"
          highlight-current-row
          @current-change="(row: ClassInfo | null) => selectedClassId = row?.id || ''"
          style="width: 100%"
        >
          <el-table-column prop="name" label="班级名称" />
          <el-table-column label="年级">
            <template #default="{ row }">{{ GRADE_LABELS[(row as ClassInfo).grade] }}</template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="assignClassPage"
          :page-size="assignClassLimit"
          :total="assignClassTotal"
          layout="prev, pager, next"
          @current-change="onAssignClassPageChange"
          style="margin-top: 8px; justify-content: flex-end"
        />
      </div>
      <p class="hint">班级表头名单不会因分配自动更改；分配不需要教师接受。</p>
      <template #footer>
        <el-button @click="assignDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!selectedClass"
          :loading="assigning"
          @click="confirmAssign"
        >
          确认分配
        </el-button>
      </template>
    </el-dialog>

    <!-- Password reset dialog -->
    <el-dialog v-model="resetDialogVisible" title="重置教师密码" width="400px">
      <p>目标账号：<strong>{{ resetTarget?.username }}</strong></p>
      <p class="warn">该账号现有登录将失效。</p>
      <el-input v-model="newPassword" type="password" placeholder="新密码" show-password />
      <div class="rule">12–128 字符。</div>
      <el-input v-model="newPasswordConfirm" type="password" placeholder="确认新密码" show-password style="margin-top: 12px;" />
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="confirmReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin { max-width: 1000px; margin: 0 auto; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.search { display: flex; gap: 12px; margin-bottom: 16px; }
.assign-field { margin: 16px 0; }
.assign-field label { display: block; margin-bottom: 6px; color: #606266; }
.hint { color: #909399; font-size: 0.85rem; }
.warn { color: #f56c6c; font-size: 0.9rem; }
.rule { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
</style>
