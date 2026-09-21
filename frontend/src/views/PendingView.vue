<script setup lang="ts">
import { ElAlert, ElButton, ElCard } from 'element-plus'
import { auth, doLogout, handleApiError } from '../auth'

const emit = defineEmits<{
  (e: 'go-settings'): void
  (e: 'logged-out'): void
}>()

async function logout() {
  try {
    await doLogout()
    emit('logged-out')
  } catch (err) {
    handleApiError(err, '退出失败')
  }
}
</script>

<template>
  <el-card>
    <h2>欢迎，{{ auth.account?.display_name || '（未填写）' }}</h2>
    <el-alert
      title="待管理员分配班级，暂不能备课"
      type="warning"
      :closable="false"
      description="请联系管理员完成班级分配后再使用备课功能。"
    />
    <div class="actions">
      <el-button type="primary" @click="$emit('go-settings')">系统设置</el-button>
      <el-button @click="logout">退出</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.actions { margin-top: 24px; display: flex; gap: 12px; }
</style>
