<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElTag,
} from 'element-plus'
import * as api from '../api'
import { auth, isAdmin } from '../auth'
import type { DailyPlan } from '../types'
import {
  MORNING_EXERCISE_LABEL,
  buildAdoptedContent,
  dailyPlanErrorMessage,
  emptyContentForm,
  isAuthError,
  serverToForm,
} from '../daily-plan-content'
import type { PlanContentForm } from '../daily-plan-content'

const props = defineProps<{
  planDate: string
  /** Admin class context; must be absent on the teacher path. */
  classId?: string
}>()

const emit = defineEmits<{
  (e: 'back'): void
}>()

type Phase = 'opening' | 'missing' | 'ready' | 'failed'

const phase = ref<Phase>('opening')
const plan = ref<DailyPlan | null>(null)
const form = ref<PlanContentForm>(emptyContentForm())
const rawLessonPlan = ref('')
const openError = ref('')
const creating = ref(false)
const saving = ref(false)

interface ConflictState {
  /** Content version the local edit was originally based on. */
  baseVersion: number
  /** expected_content_version of the last rejected submit. */
  attemptedVersion: number
  server: DailyPlan | null
}

const conflict = ref<ConflictState | null>(null)

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const canEdit = computed<boolean>(() => {
  if (!plan.value) return false
  if (isAdmin()) return true
  return plan.value.creator_id === (auth.account?.id ?? '')
})

const weekLabel = computed<string>(() => {
  if (!plan.value) return ''
  const weekday = WEEKDAY_LABELS[plan.value.weekday - 1] || ''
  return `第${plan.value.week_number}周${weekday ? ` · ${weekday}` : ''}`
})

const syncStatusLabel = computed<string>(() => {
  const state = plan.value?.weekly_sync_state
  if (!state) return ''
  return state.has_pending_projection
    ? '待更新 / 待确认（pending_projection）'
    : state.status
})

const savedDatesText = computed<string>(() => {
  const dates = plan.value?.weekly_sync_state.saved_dates || []
  return dates.length ? dates.join('、') : '（无）'
})

const missingDatesText = computed<string>(() => {
  const dates = plan.value?.weekly_sync_state.missing_dates || []
  return dates.length ? dates.join('、') : '（无）'
})

const hasCollective = computed<boolean>(() =>
  form.value.morning_games.some((group) => group.group_kind === 'collective'),
)

const hasFreeChoice = computed<boolean>(() =>
  form.value.morning_games.some((group) => group.group_kind === 'free_choice'),
)

const conflictServerRaw = computed<string>(() =>
  conflict.value?.server?.content.raw_lesson_plan ?? '（空）',
)

const conflictServerContent = computed<string>(() => {
  const content = conflict.value?.server?.content.adopted_content
  return JSON.stringify(content ?? {}, null, 2)
})

/** Admin reads need the explicit class context the plan belongs to. */
function adminClassParam(): string | undefined {
  if (!isAdmin()) return undefined
  return plan.value?.class_id ?? props.classId
}

function notifyError(err: unknown, fallback: string): void {
  if (isAuthError(err)) return
  ElMessage.error(dailyPlanErrorMessage(err, fallback))
}

function applyPlan(next: DailyPlan): void {
  plan.value = next
  form.value = serverToForm(next.content.adopted_content)
  rawLessonPlan.value = next.content.raw_lesson_plan ?? ''
  conflict.value = null
  phase.value = 'ready'
}

async function openExisting(): Promise<void> {
  phase.value = 'opening'
  openError.value = ''
  try {
    const found = await api.getDailyPlanByDate(props.planDate, props.classId)
    applyPlan(found)
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 404) {
      phase.value = 'missing'
      return
    }
    openError.value = dailyPlanErrorMessage(err, '读取日计划失败')
    phase.value = 'failed'
  }
}

async function createPlan(): Promise<void> {
  if (creating.value) return
  creating.value = true
  openError.value = ''
  try {
    const created = await api.createDailyPlan(
      props.classId
        ? { plan_date: props.planDate, class_id: props.classId }
        : { plan_date: props.planDate },
    )
    applyPlan(created)
    ElMessage.success('日计划已创建')
  } catch (err) {
    openError.value = dailyPlanErrorMessage(err, '创建日计划失败')
  } finally {
    creating.value = false
  }
}

async function enterConflict(
  planId: string,
  attemptedVersion: number,
  baseVersion: number,
): Promise<void> {
  let server: DailyPlan | null = null
  try {
    server = await api.getDailyPlan(planId, adminClassParam())
  } catch (err) {
    notifyError(err, '读取服务端最新版本失败')
  }
  conflict.value = { baseVersion, attemptedVersion, server }
}

async function save(): Promise<void> {
  const current = plan.value
  if (!current || saving.value || !canEdit.value) return
  if (conflict.value) return
  saving.value = true
  try {
    const updated = await api.patchDailyPlan(current.id, {
      expected_content_version: current.current_content_version,
      raw_lesson_plan: rawLessonPlan.value,
      adopted_content: buildAdoptedContent(form.value),
    })
    applyPlan(updated)
    ElMessage.success('保存成功')
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 409 || e.code === 'VERSION_CONFLICT') {
      await enterConflict(
        current.id,
        current.current_content_version,
        current.current_content_version,
      )
      return
    }
    notifyError(err, '保存失败，请检查网络后重试')
  } finally {
    saving.value = false
  }
}

async function resubmitLocal(): Promise<void> {
  const current = plan.value
  const state = conflict.value
  if (!current || !state?.server || saving.value) return
  const expected = state.server.current_content_version
  saving.value = true
  try {
    const updated = await api.patchDailyPlan(current.id, {
      expected_content_version: expected,
      raw_lesson_plan: rawLessonPlan.value,
      adopted_content: buildAdoptedContent(form.value),
    })
    applyPlan(updated)
    ElMessage.success('已基于服务端最新版本保存')
  } catch (err) {
    const e = err as api.ApiError
    if (e.status === 409 || e.code === 'VERSION_CONFLICT') {
      await enterConflict(current.id, expected, state.baseVersion)
      return
    }
    notifyError(err, '重新提交失败，请检查网络后重试')
  } finally {
    saving.value = false
  }
}

function discardLocal(): void {
  const server = conflict.value?.server
  if (!server) return
  applyPlan(server)
  ElMessage.info('已放弃本地修改，当前显示服务端最新版本')
}

async function reloadConflictServer(): Promise<void> {
  const state = conflict.value
  if (!state || !plan.value) return
  try {
    const latest = await api.getDailyPlan(plan.value.id, adminClassParam())
    conflict.value = { ...state, server: latest }
  } catch (err) {
    notifyError(err, '读取服务端最新版本失败')
  }
}

function addMorningGroup(kind: 'collective' | 'free_choice'): void {
  if (!canEdit.value || saving.value) return
  form.value.morning_games.push({
    group_kind: kind,
    games: [],
    focus_guidance: '',
    shared_objectives: '',
    guidance_points: '',
  })
}

function removeMorningGroup(index: number): void {
  form.value.morning_games.splice(index, 1)
}

function addMorningGame(groupIndex: number): void {
  form.value.morning_games[groupIndex].games.push({ name: '' })
}

function addPostGroup(): void {
  if (!canEdit.value || saving.value) return
  form.value.post_group_games.push({
    context_kind: 'area',
    area: '',
    games: [],
    focus_guidance: '',
    objectives: '',
    guidance: '',
    support_strategy: '',
  })
}

function removePostGroup(index: number): void {
  form.value.post_group_games.splice(index, 1)
}

function addPostGame(groupIndex: number): void {
  form.value.post_group_games[groupIndex].games.push({ name: '' })
}

function addAfternoonGame(): void {
  form.value.afternoon_outdoor.games.push({ name: '' })
}

onMounted(() => {
  void openExisting()
})
</script>

<template>
  <div class="daily-plan">
    <div class="toolbar">
      <h2>日计划 · {{ planDate }}</h2>
      <div class="actions">
        <el-tag v-if="phase === 'ready'" size="small" :type="canEdit ? 'success' : 'info'">
          {{ canEdit ? '可编辑' : '只读' }}
        </el-tag>
        <el-button @click="$emit('back')">返回日历</el-button>
      </div>
    </div>

    <el-card v-if="phase === 'opening'" class="section" v-loading="true">
      <p class="muted">正在读取日计划…</p>
    </el-card>

    <el-card v-else-if="phase === 'failed'" class="section">
      <el-alert :title="openError || '读取日计划失败'" type="error" :closable="false" />
      <div class="actions-row">
        <el-button @click="openExisting">重试</el-button>
        <el-button @click="$emit('back')">返回</el-button>
      </div>
    </el-card>

    <el-card v-else-if="phase === 'missing'" class="section">
      <p>日期 <strong>{{ planDate }}</strong> 尚无日计划。</p>
      <el-alert
        v-if="openError"
        :title="openError"
        type="error"
        :closable="false"
        class="inline-alert"
      />
      <div class="actions-row">
        <el-button type="primary" :loading="creating" @click="createPlan">创建日计划</el-button>
        <el-button @click="$emit('back')">返回</el-button>
      </div>
      <p class="muted">创建时内容为空；所有栏目均可留空保存，系统不会自动补写内容。</p>
    </el-card>

    <template v-else-if="phase === 'ready' && plan">
      <el-card class="section">
        <div class="meta">
          <span>班级：{{ plan.class_name }}（{{ GRADE_LABELS[plan.grade] || plan.grade }}）</span>
          <span>园所：{{ plan.school_name || '（未填写）' }}</span>
          <span>{{ weekLabel }}</span>
          <span>创建者：{{ plan.creator_display_name || plan.creator_id }}</span>
          <span>内容版本：v{{ plan.current_content_version }}</span>
          <span>更新时间：{{ plan.updated_at }}</span>
        </div>
        <p v-if="!canEdit" class="muted">
          本日计划由其他教师创建，当前为只读视图（后端同样拒绝非创建者保存）。
        </p>
      </el-card>

      <el-card class="section">
        <template #header>周计划同步摘要</template>
        <p>
          状态：
          <el-tag
            size="small"
            :type="plan.weekly_sync_state.has_pending_projection ? 'warning' : 'info'"
          >
            {{ syncStatusLabel }}
          </el-tag>
        </p>
        <p>本周已保存日期：{{ savedDatesText }}</p>
        <p>本周尚缺日期：{{ missingDatesText }}</p>
        <p class="muted">
          此摘要为周计划待确认投影（pending projection），不是正式周计划已确认；本环节未运行
          AI，也未生成周计划内容。
        </p>
      </el-card>

      <el-alert
        v-if="conflict"
        type="warning"
        :closable="false"
        class="section conflict-alert"
        title="内容版本冲突（409），本地编辑已保留，未被覆盖"
      >
        <div class="conflict-body">
          <p>
            本地编辑基于内容版本 v{{ conflict.baseVersion
            }}<template v-if="conflict.attemptedVersion !== conflict.baseVersion">
              ；上次提交（期望 v{{ conflict.attemptedVersion }}）被服务端拒绝
            </template>
            。
          </p>
          <template v-if="conflict.server">
            <p>
              服务端最新内容版本：
              <strong>v{{ conflict.server.current_content_version }}</strong>
              （更新于 {{ conflict.server.updated_at }}）
            </p>
            <p class="conflict-hint">
              请选择处理方式：放弃本地修改载入服务端版本，或保留本地编辑区并以服务端最新版本为基准重新提交。不会无条件覆盖服务端。
            </p>
            <h4>服务端最新内容（只读，仅供比对）</h4>
            <p class="label">原始教案：</p>
            <pre class="server-block">{{ conflictServerRaw }}</pre>
            <p class="label">结构化内容：</p>
            <pre class="server-block">{{ conflictServerContent }}</pre>
            <div class="actions-row">
              <el-button :disabled="saving" @click="discardLocal">
                放弃本地修改，载入服务端版本
              </el-button>
              <el-button type="primary" :loading="saving" @click="resubmitLocal">
                保留本地编辑，以服务端最新版本为基准重新提交
              </el-button>
            </div>
          </template>
          <template v-else>
            <p>读取服务端最新版本失败，请重试后再处理冲突。</p>
            <el-button @click="reloadConflictServer">重新读取服务端版本</el-button>
          </template>
        </div>
      </el-alert>

      <!-- 晨间体能大循环：固定展示，不自动写入载荷；服务端已有值原样回写 -->
      <el-card class="section">
        <template #header>晨间 · 体能大循环</template>
        <p class="fixed-label">固定栏目：<strong>{{ MORNING_EXERCISE_LABEL }}</strong></p>

        <div
          v-for="(group, gi) in form.morning_games"
          :key="group.group_id || `morning-${gi}`"
          class="group-block"
        >
          <div class="group-head">
            <el-tag size="small">
              {{ group.group_kind === 'collective' ? '集体游戏组' : '自主游戏组（自选）' }}
            </el-tag>
            <el-button
              v-if="canEdit"
              size="small"
              text
              type="danger"
              :disabled="saving"
              @click="removeMorningGroup(gi)"
            >
              移除该组
            </el-button>
          </div>

          <div
            v-for="(game, ggi) in group.games"
            :key="game.game_id || `morning-game-${gi}-${ggi}`"
            class="game-row"
          >
            <el-input
              v-model="game.name"
              placeholder="游戏名称"
              :disabled="!canEdit || saving"
            />
            <el-button
              v-if="canEdit"
              size="small"
              text
              type="danger"
              :disabled="saving"
              @click="group.games.splice(ggi, 1)"
            >
              删除
            </el-button>
          </div>
          <el-button
            v-if="canEdit"
            size="small"
            :disabled="saving"
            @click="addMorningGame(gi)"
          >
            添加游戏
          </el-button>

          <div class="field-grid">
            <div class="field">
              <label>重点指导</label>
              <el-input
                v-model="group.focus_guidance"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
            <div class="field">
              <label>共用目标</label>
              <el-input
                v-model="group.shared_objectives"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
            <div class="field">
              <label>指导要点</label>
              <el-input
                v-model="group.guidance_points"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
          </div>
        </div>

        <p v-if="!form.morning_games.length" class="muted">
          暂无晨间游戏组（可添加，最多一个集体组与一个自主组）
        </p>
        <div v-if="canEdit" class="actions-row">
          <el-button size="small" :disabled="hasCollective || saving" @click="addMorningGroup('collective')">
            添加集体游戏组
          </el-button>
          <el-button size="small" :disabled="hasFreeChoice || saving" @click="addMorningGroup('free_choice')">
            添加自主游戏组
          </el-button>
        </div>
      </el-card>

      <!-- 晨间谈话 -->
      <el-card class="section">
        <template #header>晨间谈话</template>
        <div class="field">
          <label>话题</label>
          <el-input v-model="form.morning_talk.topic" :disabled="!canEdit || saving" />
        </div>
        <div class="field">
          <label>问题设计</label>
          <el-input
            v-model="form.morning_talk.questions"
            type="textarea"
            :rows="3"
            :disabled="!canEdit || saving"
          />
        </div>
      </el-card>

      <!-- 集体活动 -->
      <el-card class="section">
        <template #header>集体活动</template>
        <div class="field">
          <label>活动主题</label>
          <el-input v-model="form.group_activity.theme" :disabled="!canEdit || saving" />
        </div>
        <div class="field">
          <label>目标</label>
          <el-input
            v-model="form.group_activity.objectives"
            type="textarea"
            :rows="2"
            :disabled="!canEdit || saving"
          />
        </div>
        <div class="field">
          <label>准备</label>
          <el-input
            v-model="form.group_activity.preparation"
            type="textarea"
            :rows="2"
            :disabled="!canEdit || saving"
          />
        </div>
        <div class="field-grid">
          <div class="field">
            <label>重点</label>
            <el-input
              v-model="form.group_activity.key_points"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
          <div class="field">
            <label>难点</label>
            <el-input
              v-model="form.group_activity.difficult_points"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
        </div>
        <div class="field">
          <label>过程</label>
          <el-input
            v-model="form.group_activity.process"
            type="textarea"
            :rows="5"
            :disabled="!canEdit || saving"
          />
        </div>
      </el-card>

      <!-- 集体活动后游戏 -->
      <el-card class="section">
        <template #header>集体活动后游戏</template>
        <div
          v-for="(group, gi) in form.post_group_games"
          :key="group.group_id || `post-${gi}`"
          class="group-block"
        >
          <div class="group-head">
            <el-select
              v-model="group.context_kind"
              size="small"
              class="context-select"
              :disabled="!canEdit || saving"
            >
              <el-option label="室内区域" value="area" />
              <el-option label="户外" value="outdoor" />
              <el-option label="专用室" value="special_room" />
            </el-select>
            <el-input
              v-if="group.context_kind === 'area'"
              v-model="group.area"
              size="small"
              class="area-input"
              placeholder="区域名称"
              :disabled="!canEdit || saving"
            />
            <el-button
              v-if="canEdit"
              size="small"
              text
              type="danger"
              :disabled="saving"
              @click="removePostGroup(gi)"
            >
              移除该组
            </el-button>
          </div>

          <div
            v-for="(game, ggi) in group.games"
            :key="game.game_id || `post-game-${gi}-${ggi}`"
            class="game-row"
          >
            <el-input
              v-model="game.name"
              placeholder="游戏名称"
              :disabled="!canEdit || saving"
            />
            <el-button
              v-if="canEdit"
              size="small"
              text
              type="danger"
              :disabled="saving"
              @click="group.games.splice(ggi, 1)"
            >
              删除
            </el-button>
          </div>
          <el-button v-if="canEdit" size="small" :disabled="saving" @click="addPostGame(gi)">
            添加游戏
          </el-button>

          <div class="field-grid">
            <div class="field">
              <label>重点指导</label>
              <el-input
                v-model="group.focus_guidance"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
            <div class="field">
              <label>目标</label>
              <el-input
                v-model="group.objectives"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
            <div class="field">
              <label>指导</label>
              <el-input
                v-model="group.guidance"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
            <div class="field">
              <label>支持策略</label>
              <el-input
                v-model="group.support_strategy"
                type="textarea"
                :rows="2"
                :disabled="!canEdit || saving"
              />
            </div>
          </div>
        </div>

        <p v-if="!form.post_group_games.length" class="muted">暂无集体活动后游戏组</p>
        <el-button v-if="canEdit" size="small" :disabled="saving" @click="addPostGroup">
          添加游戏组
        </el-button>
      </el-card>

      <!-- 下午户外 -->
      <el-card class="section">
        <template #header>下午户外</template>
        <div class="field">
          <label>区域名称</label>
          <el-input v-model="form.afternoon_outdoor.area" :disabled="!canEdit || saving" />
        </div>

        <div
          v-for="(game, ggi) in form.afternoon_outdoor.games"
          :key="game.game_id || `afternoon-game-${ggi}`"
          class="game-row"
        >
          <el-input v-model="game.name" placeholder="游戏名称" :disabled="!canEdit || saving" />
          <el-button
            v-if="canEdit"
            size="small"
            text
            type="danger"
            :disabled="saving"
            @click="form.afternoon_outdoor.games.splice(ggi, 1)"
          >
            删除
          </el-button>
        </div>
        <el-button v-if="canEdit" size="small" :disabled="saving" @click="addAfternoonGame">
          添加游戏
        </el-button>

        <div class="field-grid">
          <div class="field">
            <label>重点观察</label>
            <el-input
              v-model="form.afternoon_outdoor.observation_focus"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
          <div class="field">
            <label>目标</label>
            <el-input
              v-model="form.afternoon_outdoor.objectives"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
          <div class="field">
            <label>指导</label>
            <el-input
              v-model="form.afternoon_outdoor.guidance"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
          <div class="field">
            <label>支持策略</label>
            <el-input
              v-model="form.afternoon_outdoor.support_strategy"
              type="textarea"
              :rows="2"
              :disabled="!canEdit || saving"
            />
          </div>
        </div>
      </el-card>

      <!-- 反思 -->
      <el-card class="section">
        <template #header>反思</template>
        <el-input
          v-model="form.reflection"
          type="textarea"
          :rows="4"
          :disabled="!canEdit || saving"
        />
      </el-card>

      <!-- 原始教案 -->
      <el-card class="section">
        <template #header>原始教案（可选）</template>
        <el-input
          v-model="rawLessonPlan"
          type="textarea"
          :rows="6"
          :disabled="!canEdit || saving"
          placeholder="可粘贴原始教案全文；留空即为空"
        />
      </el-card>

      <div v-if="canEdit" class="actions-row footer-actions">
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!!conflict"
          @click="save"
        >
          保存
        </el-button>
        <span v-if="conflict" class="muted">
          冲突处理中：请先在上方选择放弃本地或基于服务端最新版本重新提交
        </span>
        <span v-else class="muted">内容版本 v{{ plan.current_content_version }}</span>
      </div>
      <p v-else class="muted footer-hint">
        只读视图：仅创建者与管理员可以编辑保存；本页不提供删除入口。
      </p>
    </template>
  </div>
</template>

<style scoped>
.daily-plan { max-width: 900px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; align-items: center; gap: 12px; }
.section { margin-top: 16px; }
.muted { color: #909399; font-size: 0.85rem; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 20px; color: #606266; font-size: 0.9rem; }
.actions-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.inline-alert { margin-top: 12px; }
.fixed-label { margin: 0 0 12px; color: #303133; }
.group-block {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.group-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.game-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-top: 8px; }
.field { margin-top: 8px; }
.field label { display: block; margin-bottom: 4px; color: #606266; font-size: 0.85rem; }
.field-grid .field { margin-top: 0; }
.context-select { width: 150px; }
.area-input { width: 200px; }
.footer-actions { margin-top: 20px; }
.footer-hint { margin-top: 16px; }
.conflict-alert :deep(.conflict-body) { margin-top: 4px; }
.conflict-hint { color: #b88230; font-size: 0.875rem; }
.conflict-body h4 { margin: 12px 0 6px; }
.conflict-body .label { margin: 8px 0 4px; color: #606266; font-size: 0.85rem; }
.server-block {
  margin: 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.8rem;
  max-height: 240px;
  overflow: auto;
}
</style>
