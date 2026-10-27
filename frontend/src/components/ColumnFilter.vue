<template>
  <span class="cf" :class="{ 'cf-dd-wrap': dropdown }">
    <button v-if="dropdown" ref="btn" type="button" class="input cf-dd" :class="{ active: isActive }" @click.stop="toggle">
      <span class="cf-dd-text">{{ summaryText }}</span><span class="cf-dd-caret">▾</span>
    </button>
    <button v-else ref="btn" type="button" class="cf-btn" :class="{ active: isActive }" :title="isActive ? 'Filtered — click to change' : 'Filter this column'"
      @click.stop="toggle">
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M1.5 2h13l-5 6v5l-3 1.5V8z" fill="currentColor" /></svg>
    </button>
    <Teleport to="body">
      <div v-if="open" ref="pop" class="cf-pop" :style="popStyle" @click.stop @keydown.esc="open = false">
        <div class="cf-title">{{ title }}</div>

        <!-- pick values -->
        <template v-if="type === 'values'">
          <input v-model="search" class="input cf-search" placeholder="Search…" />
          <div class="cf-quick">
            <button type="button" class="linkbtn" @click="draft = filtered.map((o) => o.value)">Select all</button>
            <button type="button" class="linkbtn" @click="draft = []">Clear</button>
          </div>
          <div class="cf-list">
            <label v-for="o in filtered.slice(0, 400)" :key="o.value" class="cf-opt">
              <input v-model="draft" type="checkbox" :value="o.value" />
              <span class="cf-label">{{ o.label ?? o.value }}</span>
              <span v-if="o.count !== undefined" class="cf-count">{{ o.count.toLocaleString('en-IN') }}</span>
            </label>
            <div v-if="!filtered.length" class="muted cf-empty">No values</div>
            <div v-if="filtered.length > 400" class="muted cf-empty">Showing 400 of {{ filtered.length }} — use search</div>
          </div>
        </template>

        <!-- date range -->
        <template v-else-if="type === 'dates'">
          <div class="cf-dates">
            <label>From <input v-model="draft.from" type="date" class="input" /></label>
            <label>To <input v-model="draft.to" type="date" class="input" /></label>
          </div>
          <div class="cf-quick">
            <button type="button" class="linkbtn" @click="quick(0)">Today</button>
            <button type="button" class="linkbtn" @click="quick(1)">Yesterday</button>
            <button type="button" class="linkbtn" @click="quick(6)">Last 7 days</button>
            <button type="button" class="linkbtn" @click="quick(29)">Last 30 days</button>
          </div>
        </template>

        <!-- text -->
        <template v-else>
          <input v-model="draft" class="input cf-search" :placeholder="placeholder || 'Starts with…'" @keydown.enter="apply" />
        </template>

        <div class="cf-actions">
          <button type="button" class="btn btn-sm btn-ghost" @click="clear">Clear filter</button>
          <button type="button" class="btn btn-sm btn-primary" @click="apply">Apply</button>
        </div>
      </div>
    </Teleport>
  </span>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  type: { type: String, default: 'values' },   // values | dates | text
  title: String,
  options: { type: Array, default: () => [] }, // [{ value, label?, count? }]
  modelValue: null,                            // array | {from,to} | string
  placeholder: String,
  dropdown: Boolean,                           // show as a dropdown box instead of a funnel icon
  allText: { type: String, default: 'All' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const btn = ref(null)
const pop = ref(null)
const search = ref('')
const draft = ref(null)
const popStyle = ref({})

const isActive = computed(() => {
  const v = props.modelValue
  if (props.type === 'values') return Array.isArray(v) && v.length > 0
  if (props.type === 'dates') return !!(v && (v.from || v.to))
  return !!(v && String(v).trim())
})

const summaryText = computed(() => {
  const v = props.modelValue
  if (!Array.isArray(v) || !v.length) return props.allText
  if (v.length === 1) {
    const o = props.options.find((x) => x.value === v[0])
    return o?.label ?? v[0]
  }
  return `${v.length} selected`
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? props.options.filter((o) => String(o.label ?? o.value).toLowerCase().includes(q)) : props.options
})

function blank() { return props.type === 'values' ? [] : props.type === 'dates' ? { from: '', to: '' } : '' }

function toggle() {
  if (open.value) { open.value = false; return }
  const v = props.modelValue
  draft.value = props.type === 'values' ? [...(v || [])] : props.type === 'dates' ? { from: v?.from || '', to: v?.to || '' } : (v || '')
  search.value = ''
  const r = btn.value.getBoundingClientRect()
  const width = 290
  const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8))
  popStyle.value = { top: `${r.bottom + 6}px`, left: `${left}px`, width: `${width}px`, visibility: 'hidden' }
  open.value = true
  nextTick(() => {
    // Keep the whole popup (and its Apply button) on screen: open below if it fits,
    // otherwise above, otherwise wherever there is more room, scrolling inside.
    const h = pop.value.offsetHeight
    const below = window.innerHeight - r.bottom - 14
    const above = r.top - 14
    let top
    let maxH = null
    if (h <= below) top = r.bottom + 6
    else if (h <= above) top = r.top - 6 - h
    else if (below >= above) { top = r.bottom + 6; maxH = below }
    else { maxH = above; top = 8 }
    popStyle.value = { top: `${top}px`, left: `${left}px`, width: `${width}px`,
      ...(maxH ? { maxHeight: `${maxH}px`, overflowY: 'auto' } : {}) }
    pop.value?.querySelector('input')?.focus()
    document.addEventListener('click', outside)
    window.addEventListener('scroll', closeIfOutside, true)
  })
}

function close() { open.value = false; document.removeEventListener('click', outside); window.removeEventListener('scroll', closeIfOutside, true) }
function outside(e) { if (pop.value && !pop.value.contains(e.target)) close() }
function closeIfOutside(e) { if (pop.value && !pop.value.contains(e.target)) close() }

function apply() { emit('update:modelValue', draft.value); close() }
function clear() { emit('update:modelValue', blank()); close() }

const iso = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(d)
function quick(daysBack) {
  const now = new Date()
  const from = new Date(now.getTime() - daysBack * 864e5)
  draft.value = daysBack === 1 ? { from: iso(from), to: iso(from) } : { from: iso(from), to: iso(now) }
}

onBeforeUnmount(close)
</script>

<style scoped>
.cf { display: inline-flex; vertical-align: middle; margin-left: 4px; }
.cf-btn {
  border: 0; background: transparent; color: var(--muted); cursor: pointer; padding: 3px; border-radius: 4px;
  display: inline-flex; align-items: center; opacity: .65;
}
.cf-dd-wrap { display: flex; margin-left: 0; }
.cf-dd { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-width: 190px;
  cursor: pointer; text-align: left; background: var(--surface); }
.cf-dd.active { border-color: var(--brand); background: var(--brand-soft); color: var(--brand); font-weight: 500; }
.cf-dd-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-dd-caret { color: var(--muted); font-size: .8rem; }
.cf-btn:hover { background: var(--border); opacity: 1; color: var(--text); }
.cf-btn.active { color: #fff; background: var(--brand); opacity: 1; }
</style>

<style>
/* teleported popover (not scoped) */
.cf-pop {
  position: fixed; z-index: 1000; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 10px;
  box-shadow: 0 10px 30px rgba(16, 24, 40, .18); padding: 12px; text-transform: none; letter-spacing: 0;
  font-size: .92rem; font-weight: 400; color: var(--text);
}
.cf-title { font-weight: 600; margin-bottom: 8px; }
.cf-search { width: 100%; }
.cf-quick { display: flex; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
.cf-quick .linkbtn { background: none; border: 0; color: var(--brand); cursor: pointer; padding: 0; font-size: .85rem; }
.cf-list { max-height: 260px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; padding: 4px 0; }
.cf-opt { display: flex; align-items: center; gap: 8px; padding: 5px 10px; cursor: pointer; }
.cf-opt:hover { background: var(--surface-2); }
.cf-opt input { width: 16px; height: 16px; flex: none; }
.cf-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-count { color: var(--muted); font-size: .8rem; font-variant-numeric: tabular-nums; }
.cf-empty { padding: 8px 10px; font-size: .85rem; }
.cf-dates { display: grid; gap: 8px; }
.cf-dates label { display: flex; flex-direction: column; gap: 4px; font-size: .8rem; font-weight: 600; color: var(--text-2); }
.cf-actions { display: flex; justify-content: space-between; margin-top: 12px; }
</style>
