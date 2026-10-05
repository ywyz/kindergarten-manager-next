<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { ElAlert, ElButton, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'
import { auth, doLogout, expectedVersion, handleApiError, reset, restoreSession } from '../auth'
import * as api from '../api'
import AiConfigCard from '../components/ai/AiConfigCard.vue'
import PromptGuidanceCard from '../components/ai/PromptGuidanceCard.vue'
import AdminPromptDefaultsCard from '../components/ai/AdminPromptDefaultsCard.vue'

const emit = defineEmits<{
  (e: 'profile-updated'): void
  (e: 'password-changed'): void
  (e: 'logged-out'): void
  (e: 'go-back'): void
}>()

const displayName = ref(auth.account?.display_name || '')
const currentPassword = ref('')
const newPassword = ref('')
const newPasswordConfirm = ref('')
const savingProfile = ref(false)
const savingPassword = ref(false)
const loggingOut = ref(false)

async function saveProfile() {
  savingProfile.value = true
  try {
    const cleaned = displayName.value.trim() || null
    const updated = await api.updateProfile({ display_name: cleaned, expected_version: expectedVersion() })
    // Use the returned account directly so the next save uses the new version.
    auth.account = updated
    ElMessage.success('姓名已保存')
    emit('profile-updated')
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'VERSION_CONFLICT') {
      // Keep the user's edit; reload the latest server state so the latest
      // display name and version are visible before they decide to retry.
      await restoreSession()
      ElMessage.warning(`账号信息已变化，服务端最新姓名为“${auth.account?.display_name || '（未填写）'}”，请确认后重新保存`)
      return
    }
    handleApiError(err, '保存失败')
  } finally {
    savingProfile.value = false
  }
}

async function changePassword() {
  if (newPassword.value !== newPasswordConfirm.value) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  savingPassword.value = true
  try {
    await api.changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
      expected_version: expectedVersion(),
    })
    ElMessage.success('密码已修改，请重新登录')
    reset()
    emit('password-changed')
  } catch (err) {
    const e = err as api.ApiError
    if (e.code === 'VERSION_CONFLICT') {
      // Clear password fields and reload the latest target version.
      currentPassword.value = ''
      newPassword.value = ''
      newPasswordConfirm.value = ''
      await restoreSession()
      ElMessage.warning('账号信息已变化，请确认后重新提交')
      return
    }
    handleApiError(err, '修改密码失败')
  } finally {
    savingPassword.value = false
  }
}

async function logout() {
  // Exit clears the in-memory key immediately, before the components go.
  aiConfigCard.value?.teardownSecretInput?.()
  loggingOut.value = true
  try {
    await doLogout()
    emit('logged-out')
  } catch (err) {
    handleApiError(err, '退出失败')
  } finally {
    loggingOut.value = false
  }
}

/**
 * 401 within any AI card: the global handler dispatches the login flow, so
 * page state simply goes down with it. The config secret input is wiped
 * immediately; nothing is persisted anywhere.
 */
function onAccountInvalid() {
  aiConfigCard.value?.teardownSecretInput()
}

const aiConfigCard = ref<{
  teardownSecretInput: () => void
  hasUnsavedChanges?: () => boolean
} | null>(null)
const promptCard = ref<{ hasUnsavedChanges?: () => boolean } | null>(null)
const adminCard = ref<{ hasUnsavedChanges?: () => boolean } | null>(null)

// --- Leaving with unsaved AI drafts (R6) -----------------------------------
// Each card reports unsaved input/drafts; leaving via 返回 or 退出登录 with
// any unsaved draft demands an explicit confirmation. Drafts stay in-page
// memory only — no browser storage of any kind. 401/logout still wipes the
// secret input immediately and unconditionally.
const leaveConfirm = ref<'back' | 'logout' | null>(null)

function cardUnsaved(): boolean {
  return (
    !!aiConfigCard.value?.hasUnsavedChanges?.() ||
    !!promptCard.value?.hasUnsavedChanges?.() ||
    !!adminCard.value?.hasUnsavedChanges?.()
  )
}

function requestLeave(kind: 'back' | 'logout') {
  if (kind === 'logout') {
    // The key is wiped immediately even when a draft confirmation appears.
    aiConfigCard.value?.teardownSecretInput()
  }
  if (cardUnsaved()) {
    leaveConfirm.value = kind
    return
  }
  if (kind === 'back') emit('go-back')
  else void logout()
}

function confirmLeave() {
  const kind = leaveConfirm.value
  leaveConfirm.value = null
  if (kind === 'back') emit('go-back')
  else void logout()
}

function cancelLeave() {
  leaveConfirm.value = null
}

onBeforeUnmount(() => {
  currentPassword.value = ''
  newPassword.value = ''
  newPasswordConfirm.value = ''
  leaveConfirm.value = null
})
</script>

<template>
  <div class="settings">
    <div class="toolbar">
      <h2>系统设置</h2>
      <div class="actions">
        <el-button @click="requestLeave('back')">返回</el-button>
        <el-button :loading="loggingOut" @click="requestLeave('logout')">退出登录</el-button>
      </div>
    </div>

    <el-alert
      v-if="leaveConfirm"
      type="warning"
      :closable="false"
      title="存在未保存的修改（AI 配置或指导文字）。离开后这些本页内存草稿将被丢弃，是否确认离开？"
      class="section"
    >
      <div class="confirm-actions">
        <el-button type="warning" @click="confirmLeave">确认离开（不保存）</el-button>
        <el-button @click="cancelLeave">留在此页继续编辑</el-button>
      </div>
    </el-alert>

    <el-card class="section">
      <template #header>修改姓名</template>
      <el-form label-position="top" @submit.prevent="saveProfile">
        <el-form-item label="姓名">
          <el-input v-model="displayName" maxlength="80" show-word-limit placeholder="未填写" />
          <div class="hint">当前保存的姓名：{{ auth.account?.display_name || '（未填写）' }}</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="savingProfile">保存姓名</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="section">
      <template #header>修改密码</template>
      <el-form label-position="top" @submit.prevent="changePassword">
        <el-form-item label="当前密码">
          <el-input v-model="currentPassword" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" autocomplete="new-password" show-password />
          <div class="rule">12–128 字符。</div>
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="newPasswordConfirm" type="password" autocomplete="new-password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="savingPassword">修改密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <AiConfigCard
      ref="aiConfigCard"
      class="section"
      @account-invalid="onAccountInvalid"
    />

    <PromptGuidanceCard
      ref="promptCard"
      class="section"
      @account-invalid="onAccountInvalid"
    />

    <AdminPromptDefaultsCard
      v-if="auth.account?.role === 'admin'"
      ref="adminCard"
      class="section"
    />
  </div>
</template>

<style scoped>
.settings { max-width: 860px; margin: 0 auto; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; gap: 12px; }
.section { margin-bottom: 24px; }
.confirm-actions { display: flex; gap: 12px; margin-top: 8px; }
.rule { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
.hint { color: #606266; font-size: 0.85rem; margin-top: 4px; line-height: 1.4; }
</style>
