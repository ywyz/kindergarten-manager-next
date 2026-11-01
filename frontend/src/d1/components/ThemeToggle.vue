<script setup lang="ts">
import { computed } from 'vue'
import type { ThemeMode } from '../theme'

const props = defineProps<{
  mode: ThemeMode
  disabled?: boolean
  pending?: boolean
}>()

const emit = defineEmits<{
  (e: 'change', mode: ThemeMode): void
}>()

const label = computed(() =>
  props.mode === 'dark' ? '切换到亮色模式' : '切换到暗色模式',
)

function toggle(): void {
  if (props.disabled) return
  emit('change', props.mode === 'dark' ? 'light' : 'dark')
}
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :aria-label="label"
    :aria-pressed="mode === 'dark'"
    :aria-busy="pending === true"
    :disabled="disabled"
    @click="toggle"
  >
    <span aria-hidden="true">{{ mode === 'dark' ? '☾' : '☀' }}</span>
    <span>{{ mode === 'dark' ? '暗色' : '亮色' }}</span>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 2rem;
  padding: 0.2rem 0.65rem;
  border: 1px solid var(--kgm-border);
  border-radius: 1rem;
  background: var(--kgm-surface);
  color: var(--kgm-text);
  cursor: pointer;
  font: inherit;
}
.theme-toggle:hover:not(:disabled) {
  border-color: var(--kgm-accent);
  color: var(--kgm-accent);
}
.theme-toggle:focus-visible {
  outline: 2px solid var(--kgm-focus);
  outline-offset: 2px;
}
.theme-toggle:disabled {
  color: var(--kgm-disabled);
  cursor: not-allowed;
}
</style>
