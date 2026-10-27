<template>
  <div class="tl" :class="tone">
    <div class="tl-head">
      <span class="pill" :class="tone">{{ title }}</span>
      <span v-if="record?.found" class="muted">{{ record.tracking_count }} event{{ record.tracking_count === 1 ? '' : 's' }}</span>
      <span v-if="record?.records_found > 1" class="pill warn" title="Multiple documents share this AWB; showing the most recent">
        {{ record.records_found }} records
      </span>
    </div>
    <div v-if="!record?.found" class="muted none">Not found in {{ title }}</div>
    <div v-else-if="!record.tracking?.length" class="muted none">No tracking events</div>
    <ol v-else class="events">
      <li v-for="(e, i) in shown" :key="i" :class="{ latest: i === 0 }">
        <div class="when mono">{{ fmtDateTime(e.datetime) }}</div>
        <div class="what">
          <strong>{{ e.status || '—' }}</strong>
          <span v-if="e.code" class="code mono">{{ e.code }}</span>
          <div v-if="e.location || e.remark" class="where">
            <span v-if="e.location">{{ e.location }}</span>
            <span v-if="e.location && e.remark && e.remark !== e.status"> · </span>
            <span v-if="e.remark && e.remark !== e.status" class="muted">{{ e.remark }}</span>
          </div>
        </div>
      </li>
    </ol>
    <button v-if="record?.tracking?.length > limit" class="btn btn-ghost btn-sm" @click="all = !all">
      {{ all ? 'Show less' : `Show all ${record.tracking.length}` }}
    </button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { fmtDateTime } from '../format'

const props = defineProps({ record: Object, title: String, tone: String })
const limit = 8
const all = ref(false)
const shown = computed(() => (all.value ? props.record.tracking : props.record.tracking.slice(0, limit)))
</script>

<style scoped>
.tl { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; min-width: 0; }
.tl.st { border-top: 3px solid var(--st); } .tl.pf { border-top: 3px solid var(--pf); }
.tl-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.none { padding: 10px 0; }
.events { list-style: none; margin: 0; padding: 0; }
.events li { display: grid; grid-template-columns: 150px 1fr; gap: 14px; padding: 8px 0 8px 16px; position: relative; border-left: 2px solid var(--border); margin-left: 4px; }
.events li::before { content: ''; position: absolute; left: -6px; top: 13px; width: 10px; height: 10px; border-radius: 50%; background: var(--border-strong); }
.events li.latest::before { background: var(--brand); box-shadow: 0 0 0 3px var(--brand-soft); }
.when { color: var(--text-2); font-size: .85rem; padding-top: 2px; }
.what strong { font-weight: 600; }
.code { font-size: .78rem; color: var(--muted); margin-left: 8px; }
.where { font-size: .88rem; color: var(--text-2); margin-top: 2px; }
@media (max-width: 600px) { .events li { grid-template-columns: 1fr; gap: 2px; } }
</style>
