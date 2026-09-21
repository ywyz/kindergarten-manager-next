<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'
import { doLogin } from '../auth'
import { handleApiError } from '../auth'

const emit = defineEmits<{
  (e: 'logged-in'): void
  (e: 'go-register'): void
}>()

const username = ref('')
const password = ref('')
const submitting = ref(false)

async function submit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  submitting.value = true
  try {
    await doLogin(username.value, password.value)
    ElMessage.success('登录成功')
    emit('logged-in')
  } catch (err) {
    handleApiError(err, '登录失败')
  } finally {
    submitting.value = false
    password.value = ''
  }
}
</script>

<template>
  <el-card class="auth-card">
    <h2>登录</h2>
    <el-form label-position="top" @submit.prevent="submit">
      <el-form-item label="用户名">
        <el-input v-model="username" autocomplete="username" />
        <div class="rule">去首尾空格并转小写，3–32 位英文字母、数字、下划线、连字符或点，至少包含一位字母或数字。</div>
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="password" type="password" autocomplete="current-password" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting">登录</el-button>
        <el-button link @click="$emit('go-register')">去注册</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.auth-card { max-width: 400px; margin: 64px auto; }
h2 { margin-top: 0; }
.rule { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
</style>
