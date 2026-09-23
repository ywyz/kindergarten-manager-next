<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import * as api from '../api'
import { handleApiError } from '../auth'
import type { ClassInfo } from '../types'
import WeeklyPlanListView from './WeeklyPlanListView.vue'
import WeeklyPlanView from './WeeklyPlanView.vue'

/**
 * Admin entry into the I4 closure: pick a class explicitly, then read the
 * existing weekly plans of that class (list -> detail). Admins never get a
 * create action here; every request carries the explicit class_id.
 */
const classes = ref<ClassInfo[]>([])
const classesLoading = ref(false)
const classId = ref('')
const planId = ref('')

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

async function loadClasses(): Promise<void> {
  classesLoading.value = true
  try {
    const res = await api.listClasses({ offset: 0, limit: 100 })
    classes.value = res.items
  } catch (err) {
    handleApiError(err, '加载班级列表失败')
  } finally {
    classesLoading.value = false
  }
}

function closePlan(): void {
  planId.value = ''
}

watch(classId, () => {
  // Switching class invalidates any open detail of the previous class.
  planId.value = ''
})

onMounted(() => {
  void loadClasses()
})
</script>

<template>
  <div class="admin-weekly">
    <template v-if="!planId">
      <el-card>
        <template #header>
          <div class="card-head">
            <el-select
              v-model="classId"
              placeholder="选择班级（管理员按班级查看周计划）"
              clearable
              :loading="classesLoading"
              style="width: 300px"
            >
              <el-option
                v-for="item in classes"
                :key="item.id"
                :label="`${item.name}（${GRADE_LABELS[item.grade] || item.grade}）`"
                :value="item.id"
              />
            </el-select>
          </div>
        </template>

        <WeeklyPlanListView
          v-if="classId"
          :class-id="classId"
          :show-back="false"
          @open="(id: string) => (planId = id)"
        />
        <p v-else class="muted">请先选择班级，再查看该班已有周计划。</p>
        <p class="hint">
          管理员不提供周计划创建入口；周计划由教师在班级日历中按学期周次创建。
        </p>
      </el-card>
    </template>

    <WeeklyPlanView
      v-else
      :plan-id="planId"
      :class-id="classId"
      @back="closePlan"
    />
  </div>
</template>

<style scoped>
.admin-weekly { display: flex; flex-direction: column; gap: 16px; }
.card-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.muted { color: #909399; font-size: 0.85rem; }
.hint { color: #909399; font-size: 0.85rem; margin-top: 10px; }
</style>
