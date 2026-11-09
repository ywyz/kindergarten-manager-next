<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import {
  cloneCurriculumContent,
  emptyCurriculumContent,
  formatCurriculumUpdatedAt,
  listCurriculumDeliberations,
  newCurriculumRecordId,
  type CurriculumContent,
  type CurriculumListRecord,
} from '../curriculum'

const props = defineProps<{
  frozen?: boolean
  disabled?: boolean
  profileEpoch?: number
}>()

const emit = defineEmits<{
  (
    e: 'open-record',
    recordId: string,
    isNew: boolean,
    defaults: CurriculumContent | null,
  ): void
  (e: 'back'): void
}>()

const records = ref<CurriculumListRecord[]>([])
const defaults = ref<CurriculumContent>(emptyCurriculumContent())
const defaultsReady = ref(false)
const loading = ref(false)
const loadError = ref('')
let loadSeq = 0
let lifecycle = 0
let unmounted = false

const canNavigate = computed(() => !props.frozen && !props.disabled)
async function load(): Promise<void> {
  const seq = ++loadSeq
  const generation = lifecycle
  loading.value = true
  loadError.value = ''
  try {
    const data = await listCurriculumDeliberations()
    if (seq !== loadSeq || generation !== lifecycle || unmounted) return
    records.value = data.records
    defaults.value = cloneCurriculumContent(data.defaults)
    defaultsReady.value = true
  } catch (error) {
    if (seq !== loadSeq || generation !== lifecycle || unmounted) return
    loadError.value =
      error instanceof ApiError
        ? error.message
        : `读取失败：${String(error)}`
  } finally {
    if (seq === loadSeq && generation === lifecycle && !unmounted) {
      loading.value = false
    }
  }
}

async function createNew(): Promise<void> {
  if (!canNavigate.value) return
  if (!defaultsReady.value) {
    await load()
    if (!defaultsReady.value) return
  }
  emit(
    'open-record',
    newCurriculumRecordId(),
    true,
    cloneCurriculumContent(defaults.value),
  )
}

function openRecord(item: CurriculumListRecord): void {
  if (!canNavigate.value) return
  emit('open-record', item.id, false, null)
}

function back(): void {
  if (!canNavigate.value) return
  emit('back')
}

function resetForContext(): void {
  lifecycle += 1
  loadSeq += 1
  loading.value = false
  loadError.value = ''
  defaultsReady.value = false
  records.value = []
  defaults.value = emptyCurriculumContent()
  void load()
}

watch(
  () => props.profileEpoch ?? 0,
  () => resetForContext(),
)

onMounted(() => {
  void load()
})

onBeforeUnmount(() => {
  unmounted = true
  lifecycle += 1
  loadSeq += 1
})

defineExpose({ reload: load, resetForContext })
</script>
<template>
  <div class="curriculum-plans">
    <div class="topbar">
      <div>
        <h2>课程审议</h2>
        <p class="muted">按一次活动保存一份记录；同名活动按各自记录区分。</p>
      </div>
      <div class="actions">
        <el-button
          data-d1="curriculum-back"
          :disabled="!canNavigate"
          @click="back"
        >
          返回工作台
        </el-button>
        <el-button
          type="primary"
          data-d1="curriculum-create"
          :disabled="!canNavigate"
          @click="createNew"
        >
          新建课程审议
        </el-button>
      </div>
    </div>

    <el-card shadow="never" class="block">
      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        :title="loadError"
        class="block"
      >
        <el-button size="small" @click="load">重试</el-button>
      </el-alert>

      <el-table
        v-loading="loading"
        :data="records"
        data-d1="curriculum-plans-table"
        empty-text="本班还没有课程审议记录"
      >
        <el-table-column label="活动名称" min-width="220">
          <template #default="{ row }">
            <el-button link type="primary" @click="openRecord(row)">
              {{ row.activity_name || '（未填写活动名称）' }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="activity_date" label="活动时间" width="130" />
        <el-table-column label="最近保存" width="170">
          <template #default="{ row }">
            {{ formatCurriculumUpdatedAt(row.updated_at) || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column label="" width="110">
          <template #default="{ row }">
            <el-button
              size="small"
              data-d1="curriculum-open"
              @click="openRecord(row)"
            >
              继续填写
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.curriculum-plans {
  padding: 16px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.actions {
  display: flex;
  gap: 8px;
}
.block {
  margin-top: 12px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
</style>