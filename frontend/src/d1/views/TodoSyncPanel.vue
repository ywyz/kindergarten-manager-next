<script setup lang="ts">
/**
 * Optional Nextcloud Tasks (CalDAV) linkage panel (settings page).
 *
 * Default off.  The teacher connects an account, picks exactly one task
 * list and then explicitly chooses 「双向同步所选清单（新增、编辑和完
 * 成）」.  The Nextcloud password is submitted once to the local API and
 * stored only in the machine-local DPAPI store: never in this page's
 * state, never in the local database, never in a backup.  Deleting is
 * never part of the linkage in either direction.
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createTodoSyncStore,
  type TodoSyncListView,
} from '../todoSync'

const props = withDefaults(defineProps<{
  frozen?: boolean
}>(), { frozen: false })
const emit = defineEmits<{
  (e: 'enabled-change', value: boolean): void
}>()

const store = createTodoSyncStore()
const state = store.state

const serverUrl = ref('')
const username = ref('')
const password = ref('')
const chosenHref = ref('')
const viewLoaded = ref(false)

const canConnect = computed(() =>
  !props.frozen
  && !state.connecting
  && !!serverUrl.value.trim()
  && !!username.value.trim()
  && !!password.value,
)
const canSelect = computed(() =>
  !props.frozen
  && !state.selecting
  && !!chosenHref.value,
)
const connected = store.connected
const credentialReady = store.credentialReady
const enabled = store.enabled
/**
 * The reconnect form shows whenever the saved password is unusable (after
 * 「停止并清除本机密码」, after a restore, or a DPAPI refusal): the account
 * row alone is not a working linkage, and the stale list table must never
 * render without a working credential.
 */
const showConnectForm = computed(
  () => !connected.value || !credentialReady.value,
)

onMounted(async () => {
  await store.loadStatus()
  const setting = state.status?.setting
  if (setting?.server_url) serverUrl.value = setting.server_url
  if (setting?.username) username.value = setting.username
  if (state.error) state.error = ''
  viewLoaded.value = true
  // Opening the settings panel never starts a sync or a network listing by
  // itself when the linkage is not usable; lists load only for a working
  // credential, and a refresh stays teacher-initiated otherwise.
  if (connected.value && credentialReady.value) void store.loadLists()
})

async function connectAction(): Promise<void> {
  if (!canConnect.value) return
  const ok = await store.connect({
    url: serverUrl.value.trim(),
    username: username.value.trim(),
    password: password.value,
  })
  password.value = ''
  if (ok) {
    await store.loadLists()
    chosenHref.value = state.selectedHref
  }
}

function selectList(list: TodoSyncListView): void {
  if (props.frozen || state.selecting) return
  chosenHref.value = list.href
}

async function enableAction(): Promise<void> {
  if (!canSelect.value) return
  const ok = await store.selectList(chosenHref.value)
  if (ok) emit('enabled-change', true)
}

async function syncAction(): Promise<void> {
  if (props.frozen || state.syncing || !enabled.value) return
  await store.syncNow()
}

async function disableAction(clear: boolean): Promise<void> {
  if (props.frozen || state.syncing) return
  if (clear) {
    try {
      await ElMessageBox.confirm(
        '停止联动并清除本机保存的 Nextcloud 密码？清单与待办不会被删除。',
        '停止联动',
        { confirmButtonText: '停止并清除', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  const ok = await store.disable(clear)
  if (ok) {
    emit('enabled-change', false)
    if (clear) {
      // 「停止并清除」 removes the machine password: the stale list table
      // must disappear and the reconnect form takes over immediately.
      store.resetLocal()
    }
    ElMessage.success(state.notice)
  }
}
</script>

<template>
  <div class="kgm-sheet" data-d1="todo-sync-panel">
    <div class="kgm-sheet-header">
      Nextcloud 待办双向同步
      <span class="muted">默认关闭；仅同步所选清单的新增、编辑和完成</span>
    </div>
    <p class="muted sheet-note" data-d1="todo-sync-note">
      连接后可把个人待办与 Nextcloud Tasks 清单双向同步（新增、编辑、完成）。
      删除不会在两端传播：本地删除不会动远端任务，远端删除后本地保留。
      双方同时修改的条目不会互相覆盖，只提示冲突。
    </p>
    <p class="muted sheet-note" data-d1="todo-sync-privacy-note">
      Nextcloud 密码只保存在本机受保护存储（DPAPI），不写入本页、本地数据库、
      备份包或日志；两台电脑各自连接同一账号即可使用。
    </p>

    <el-alert
      v-if="state.error"
      type="error"
      :closable="false"
      class="todo-sync-notice"
      data-d1="todo-sync-error"
      :title="state.error"
    />
    <el-alert
      v-if="state.notice"
      type="success"
      :closable="false"
      class="todo-sync-notice"
      data-d1="todo-sync-notice"
      :title="state.notice"
    />

    <el-alert
      v-if="connected && !credentialReady && viewLoaded"
      type="warning"
      :closable="false"
      class="todo-sync-notice"
      data-d1="todo-sync-credential-warning"
      title="本机保存的 Nextcloud 密码不可用：请重新输入密码完成连接，或停止并清除后重新连接。"
    />

    <div v-if="!viewLoaded" class="muted sheet-note">正在读取本机同步状态…</div>

    <template v-else-if="showConnectForm">
      <p v-if="connected" class="muted sheet-note" data-d1="todo-sync-account-kept">
        连接信息（{{ state.status?.setting.server_url }}，用户
        {{ state.status?.setting.username }}）仍保留在本机；重新输入应用密码即可继续使用。
      </p>
      <div class="todo-sync-field">
        <span class="muted">Nextcloud 地址（https）</span>
        <el-input
          v-model="serverUrl"
          :disabled="props.frozen || state.connecting"
          placeholder="https://cloud.example.com/"
          data-d1="todo-sync-url"
        />
      </div>
      <div class="todo-sync-field">
        <span class="muted">用户名</span>
        <el-input
          v-model="username"
          :disabled="props.frozen || state.connecting"
          autocomplete="username"
          data-d1="todo-sync-username"
        />
      </div>
      <div class="todo-sync-field">
        <span class="muted">应用密码</span>
        <el-input
          v-model="password"
          type="password"
          autocomplete="new-password"
          :disabled="props.frozen || state.connecting"
          data-d1="todo-sync-password"
        />
      </div>
      <div class="actions">
        <el-button
          type="primary"
          :loading="state.connecting"
          :disabled="!canConnect"
          data-d1="todo-sync-connect"
          @click="connectAction"
        >
          连接 Nextcloud
        </el-button>
      </div>
    </template>

    <template v-else>
      <p class="muted sheet-note" data-d1="todo-sync-account">
        已连接：{{ state.status?.setting.server_url }}（用户 {{ state.status?.setting.username }}）
      </p>

      <div v-if="state.lists.length" class="todo-sync-lists" data-d1="todo-sync-lists">
        <p class="muted sheet-note">选择一个清单（支持任务的清单已排前）：</p>
        <table class="kgm-preview-table" data-d1="todo-sync-list-table">
          <thead>
            <tr><th>清单</th><th>支持任务</th><th>选择</th></tr>
          </thead>
          <tbody>
            <tr v-for="list in state.lists" :key="list.href">
              <td>{{ list.display_name }}</td>
              <td>{{ list.supports_vtodo ? '是' : '未声明' }}</td>
              <td>
                <el-radio
                  :model-value="chosenHref"
                  :value="list.href"
                  :disabled="props.frozen || state.selecting || enabled"
                  :data-d1="`todo-sync-list-${list.href}`"
                  @update:model-value="selectList(list)"
                >
                  选择
                </el-radio>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!enabled" class="actions">
        <el-button
          :loading="state.loading"
          :disabled="props.frozen"
          data-d1="todo-sync-refresh-lists"
          @click="store.loadLists()"
        >
          刷新清单
        </el-button>
        <el-button
          type="primary"
          :disabled="!canSelect"
          :loading="state.selecting"
          data-d1="todo-sync-enable"
          @click="enableAction"
        >
          双向同步所选清单（新增、编辑和完成）
        </el-button>
        <el-button
          :disabled="props.frozen || state.syncing"
          data-d1="todo-sync-disable-keep"
          @click="disableAction(false)"
        >
          停止联动
        </el-button>
      </div>

      <div v-else class="actions">
        <el-button
          type="primary"
          :loading="state.syncing"
          :disabled="props.frozen"
          data-d1="todo-sync-run"
          @click="syncAction"
        >
          立即同步
        </el-button>
        <el-button
          :disabled="props.frozen || state.syncing"
          data-d1="todo-sync-disable"
          @click="disableAction(false)"
        >
          停止联动
        </el-button>
        <el-button
          :disabled="props.frozen || state.syncing"
          data-d1="todo-sync-disable-clear"
          @click="disableAction(true)"
        >
          停止并清除本机密码
        </el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.todo-sync-field {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  max-width: 480px;
}
.todo-sync-lists {
  margin-top: 10px;
}
.todo-sync-notice {
  margin-top: 10px;
}
.actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
