<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElInput,
  ElMessage,
  ElPagination,
  ElTable,
  ElTableColumn,
} from 'element-plus'
import type { Account } from '../types'
import { auth, doLogout, expectedVersion, handleApiError } from '../auth'
import * as api from '../api'

const emit = defineEmits<{
  (e: 'go-settings'): void
  (e: 'logged-out'): void
}>()

const teachers = ref<Account[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const query = ref('')
const loading = ref(false)

const resetDialogVisible = ref(false)
const resetTarget = ref<Account | null>(null)
const newPassword = ref('')
const newPasswordConfirm = ref('')
const resetting = ref(false)

const page = computed({
  get: () => Math.floor(offset.value / limit.value) + 1,
  set: (p) => { offset.value = (p - 1) * limit.value },
})

function clearResetForm() {
  resetTarget.value = null
  newPassword.value = ''
  newPasswordConfirm.value = ''
}

async function load() {
  loading.value = true
  try {
    const res = await api.listTeachers({ offset: offset.value, limit: limit.value, q: query.value || undefined })
    teachers.value = res.items
    total.value = res.total
    limit.value = res.limit
    // If the current reset target is no longer visible, cancel the operation.
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

function openReset(row: Account) {
  resetTarget.value = row
  newPassword.value = ''
  newPasswordConfirm.value = ''
  resetDialogVisible.value = true
}

watch(resetDialogVisible, (visible) => {
  if (!visible) {
    clearResetForm()
  }
})

onBeforeUnmount(() => {
  clearResetForm()
})

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
      // Clear sensitive input and reload the list so the operator sees the
      // latest target version before explicitly resubmitting.
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

onMounted(load)
</script>

<template>
  <div class="admin">
    <div class="toolbar">
      <h2>教师账号管理</h2>
      <div class="actions">
        <el-button @click="$emit('go-settings')">系统设置</el-button>
        <el-button @click="logout">退出</el-button>
      </div>
    </div>

    <el-card>
      <div class="search">
        <el-input v-model="query" placeholder="搜索用户名或姓名" clearable @change="offset = 0; load()" />
        <el-button type="primary" @click="offset = 0; load()">搜索</el-button>
      </div>
      <el-table :data="teachers" v-loading="loading" style="width: 100%">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="display_name" label="姓名">
          <template #default="{ row }">
            {{ row.display_name || '（未填写）' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" @click="openReset(row as Account)">重置密码</el-button>
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
.admin { max-width: 900px; margin: 0 auto; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.search { display: flex; gap: 12px; margin-bottom: 16px; }
.warn { color: #f56c6c; font-size: 0.9rem; }
.rule { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
</style>
