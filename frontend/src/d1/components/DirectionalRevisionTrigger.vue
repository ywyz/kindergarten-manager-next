<script setup lang="ts">
const props = defineProps<{
  disabled?: boolean
  testId?: string
  editLabel?: string
  wholeLabel?: string
}>()
const emit = defineEmits<{
  (e: 'request', whole: boolean): void
}>()

function choose(whole: boolean | string): void {
  if (props.disabled) return
  emit('request', whole === true)
}
</script>

<template>
  <el-dropdown
    trigger="click"
    :disabled="props.disabled"
    @command="choose"
  >
    <el-button
      size="small"
      text
      :disabled="props.disabled"
      :data-d1="props.testId ? `${props.testId}` : undefined"
    >
      {{ props.editLabel ?? '让 AI 修改' }} ▾
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item
          :command="false"
          :disabled="props.disabled"
          :data-d1="props.testId ? `${props.testId}-edit` : undefined"
        >
          {{ props.editLabel ?? '修改选段' }}
        </el-dropdown-item>
        <el-dropdown-item
          :command="true"
          :disabled="props.disabled"
          :data-d1="props.testId ? `${props.testId}-whole` : undefined"
        >
          {{ props.wholeLabel ?? '整栏修改' }}
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
:deep(.el-dropdown) {
  display: inline-flex;
}
</style>
