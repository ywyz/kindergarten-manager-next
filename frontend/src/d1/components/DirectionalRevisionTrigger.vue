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
</script>

<template>
  <span class="directional-trigger">
    <el-button
      size="small"
      text
      :disabled="props.disabled"
      :data-d1="props.testId ? `${props.testId}-edit` : undefined"
      @click="emit('request', false)"
    >
      {{ props.editLabel ?? '让 AI 修改这里' }}
    </el-button>
    <el-button
      size="small"
      text
      :disabled="props.disabled"
      :data-d1="props.testId ? `${props.testId}-whole` : undefined"
      @click="emit('request', true)"
    >
      {{ props.wholeLabel ?? '整栏修改' }}
    </el-button>
  </span>
</template>

<style scoped>
.directional-trigger {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}
</style>