<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'
import * as api from '../api'
import { handleApiError } from '../auth'

const emit = defineEmits<{
  (e: 'registered'): void
  (e: 'go-login'): void
}>()

const username = ref('')
const password = ref('')
const passwordConfirm = ref('')
const submitting = ref(false)

async function submit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  if (password.value !== passwordConfirm.value) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  submitting.value = true
  try {
    await api.register({ username: username.value, password: password.value })
    ElMessage.success('注册成功，请登录')
    emit('registered')
  } catch (err) {
    const e = err as { status?: number }
    if (!e.status || e.status >= 500) {
      ElMessage.warning('注册请求未收到明确结果，注册可能已完成，可用原用户名尝试登录')
    } else {
      handleApiError(err, '注册失败')
    }
  } finally {
    submitting.value = false
    password.value = ''
    passwordConfirm.value = ''
  }
}
</script>

<template>
  <el-card class="auth-card">
    <h2>注册</h2>
    <p class="hint">首个注册账号将成为管理员；后续账号为待分配教师。</p>
    <el-form label-position="top" @submit.prevent="submit">
      <el-form-item label="用户名">
        <el-input v-model="username" autocomplete="username" />
        <div class="rule">去首尾空格并转小写，3–32 位英文字母、数字、下划线、连字符或点，至少包含一位字母或数字。</div>
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="password" type="password" autocomplete="new-password" show-password />
        <div class="rule">12–128 字符，不裁剪，允许粘贴。</div>
      </el-form-item>
      <el-form-item label="确认密码">
        <el-input v-model="passwordConfirm" type="password" autocomplete="new-password" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting">注册</el-button>
        <el-button link @click="$emit('go-login')">已有账号？登录</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.auth-card { max-width: 400px; margin: 64px auto; }
h2 { margin-top: 0; }
.hint { color: #606266; font-size: 0.9rem; }
.rule { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
</style>
