<template>
  <div ref="root" class="cp">
    <button type="button" class="btn" @click.stop="open = !open">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M1 2h4v12H1zM6 2h4v12H6zM11 2h4v12h-4z" fill="currentColor" opacity=".8" /></svg>
      Columns <span class="muted">({{ modelValue.length }}/{{ columns.length }})</span>
    </button>
    <div v-if="open" class="cp-pop" @click.stop>
      <div class="cp-head">
        <strong>Show columns</strong>
        <span>
          <button type="button" class="linkbtn" @click="emit('update:modelValue', columns.map((c) => c.key))">All</button>
          <button type="button" class="linkbtn" @click="emit('update:modelValue', defaults)">Default</button>
        </span>
      </div>
      <template v-for="c in columns" :key="c.key">
        <div v-if="c.group" class="cp-group">{{ c.group }}</div>
        <label class="cp-opt" :class="{ locked: c.locked }">
          <input type="checkbox" :checked="c.locked || modelValue.includes(c.key)" :disabled="c.locked" @change="flip(c.key)" />
          {{ c.label }}<span v-if="c.locked" class="muted"> (always)</span>
        </label>
      </template>
      <div class="muted cp-note">The CSV download includes only the columns shown.</div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  columns: Array,       // [{ key, label, group?, locked? }]
  modelValue: Array,    // visible keys
  defaults: Array,
})
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const root = ref(null)

function flip(key) {
  const set = new Set(props.modelValue)
  set.has(key) ? set.delete(key) : set.add(key)
  emit('update:modelValue', props.columns.map((c) => c.key).filter((k) => set.has(k)))
}
const outside = (e) => { if (root.value && !root.value.contains(e.target)) open.value = false }
onMounted(() => document.addEventListener('click', outside))
onBeforeUnmount(() => document.removeEventListener('click', outside))
</script>

<style scoped>
.cp { position: relative; }
.cp-pop {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 50; width: 280px; background: var(--surface);
  border: 1px solid var(--border-strong); border-radius: 10px; box-shadow: 0 10px 30px rgba(16, 24, 40, .18); padding: 12px;
  max-height: 70vh; overflow-y: auto;
}
.cp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.cp-head .linkbtn { background: none; border: 0; color: var(--brand); cursor: pointer; margin-left: 10px; font-size: .85rem; }
.cp-group { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; margin: 10px 0 4px; }
.cp-opt { display: flex; align-items: center; gap: 8px; padding: 5px 4px; cursor: pointer; border-radius: 6px; }
.cp-opt:hover { background: var(--surface-2); }
.cp-opt.locked { cursor: default; }
.cp-opt input { width: 16px; height: 16px; }
.cp-note { font-size: .8rem; margin-top: 10px; }
</style>
