<template>
  <div class="page">
    <section class="card card-pad input-card">
      <div class="input-row">
        <div class="field grow">
          <label for="awbs">AWB numbers</label>
          <textarea id="awbs" v-model="raw" class="input mono awb-input" rows="4" spellcheck="false"
            placeholder="Paste one or many AWBs — separated by new lines, commas or spaces"
            @keydown.ctrl.enter="run" @keydown.meta.enter="run" />
        </div>
        <div class="actions">
          <div class="count"><strong class="num">{{ parsed.length }}</strong> AWB{{ parsed.length === 1 ? '' : 's' }}
            <span v-if="parsed.length > maxAwbs" class="tone-bad"> · max {{ maxAwbs }}</span></div>
          <button class="btn btn-primary" :disabled="!parsed.length || loading || parsed.length > maxAwbs" @click="run">
            <span v-if="loading" class="spinner"></span>{{ loading ? 'Checking…' : 'Check status' }}
          </button>
          <button class="btn btn-ghost" :disabled="!raw" @click="clear">Clear</button>
        </div>
      </div>
      <div class="hint muted">Checks {{ labels.smart_tracking }} first, then {{ labels.platform }}. Ctrl + Enter to run.</div>
    </section>

    <div v-if="error" class="error">{{ error }}</div>

    <template v-if="result">
      <div v-if="closedCount" class="closed-note" :class="{ showing: showClosed }">
        <template v-if="!showClosed">
          <strong>{{ closedCount }}</strong> AWB{{ closedCount > 1 ? 's' : '' }} skipped — closed status
          ({{ closedNames }}).
          <button class="linkbtn" @click="showClosed = true">Show them</button>
        </template>
        <template v-else>
          Showing closed AWBs too ({{ closedCount }}).
          <button class="linkbtn" @click="showClosed = false">Skip closed AWBs</button>
        </template>
      </div>
      <section class="chips">
        <button v-for="c in chips" :key="c.key" class="chip" :class="[c.tone, { active: activeChip === c.key }]"
          :disabled="!c.count && c.key !== 'all'" @click="setChip(c.key)">
          <span class="chip-num num">{{ c.count }}</span><span>{{ c.label }}</span>
        </button>
      </section>

      <section class="card">
        <div class="toolbar">
          <div class="muted">
            Showing <strong class="num">{{ visibleRows.length }}</strong> of {{ baseRows.length }}
            <template v-if="activeFilterCount"> · {{ activeFilterCount }} column filter{{ activeFilterCount > 1 ? 's' : '' }}
              <button class="linkbtn" @click="clearFilters">Clear all filters</button></template>
            · <button class="linkbtn" @click="expandAll">Expand all</button>
            · <button class="linkbtn" @click="expanded = new Set()">Collapse all</button>
          </div>
          <div class="tools">
            <ColumnPicker v-model="visible" :columns="pickerColumns" :defaults="defaultVisible" />
            <button class="btn" :disabled="!visibleRows.length" @click="exportCsv">Export CSV</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="grid results">
            <thead>
              <tr>
                <th rowspan="2" class="awb-col">AWB No.
                  <ColumnFilter v-model="filters.awb" type="text" title="AWB No." placeholder="Contains…" /></th>
                <th v-for="g in groupsShown" :key="g.key" :colspan="g.cols.length" class="grp" :class="g.key">{{ g.label }}</th>
                <th v-if="show('sync')" rowspan="2">Sync
                  <ColumnFilter v-model="filters.sync" title="Sync" :options="options('sync')" /></th>
              </tr>
              <tr>
                <template v-for="g in groupsShown" :key="g.key">
                  <th v-for="(c, i) in g.cols" :key="c.key" :class="['sub', g.key, { first: i === 0 }]">
                    {{ c.label }}
                    <ColumnFilter v-model="filters[`${g.key}.${c.key}`]" :type="c.type" :title="`${g.label}: ${c.label}`"
                      :options="options(`${g.key}.${c.key}`)" />
                  </th>
                </template>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in visibleRows" :key="r.awb">
                <tr :class="{ open: expanded.has(r.awb), 'closed-row': r.closed }" @click="toggle(r.awb)">
                  <td class="awb-col mono nowrap"><span class="caret">{{ expanded.has(r.awb) ? '▾' : '▸' }}</span>{{ r.awb }}
                    <span v-if="r.closed" class="pill closed-pill">Closed</span></td>
                  <template v-for="g in groupsShown" :key="g.key">
                    <template v-if="rec(r, g.key).found">
                      <td v-for="(c, i) in g.cols" :key="c.key" :class="[g.key, { first: i === 0 }, c.type === 'dates' ? 'nowrap' : '']">
                        <template v-if="c.key === 'status'">
                          <span class="status">{{ rec(r, g.key).current_status || '—' }}</span>
                          <span v-if="rec(r, g.key).status_unmapped" class="unmapped"
                            title="This value is not a dispatch status from the mapping file - the Current status field may be wrong. Check Settings.">⚠ not a dispatch status</span>
                          <div v-if="rec(r, g.key).status_code" class="muted small mono">{{ rec(r, g.key).status_code }}</div>
                        </template>
                        <template v-else-if="c.key === 'pickup_date'">{{ fmtDate(rec(r, g.key).pickup_date) }}</template>
                        <template v-else-if="c.key === 'last_track'">
                          {{ fmtDateTime(rec(r, g.key).last_track_datetime) }}
                          <div class="small" :class="'tone-' + ageTone(hoursSince(rec(r, g.key).last_track_datetime))">
                            {{ fmtAge(hoursSince(rec(r, g.key).last_track_datetime)) }}</div>
                        </template>
                        <template v-else-if="c.key === 'tracking'">
                          <span v-if="rec(r, g.key).tracking?.length" class="latest-ev">{{ rec(r, g.key).tracking[0].status }}
                            <span class="muted small">· {{ rec(r, g.key).tracking_count }} events</span></span>
                          <span v-else class="muted">No events</span>
                        </template>
                        <template v-else-if="c.type === 'dates'">{{ fmtDateTime(c.get(rec(r, g.key))) }}</template>
                        <template v-else>{{ c.get(rec(r, g.key)) || '—' }}</template>
                      </td>
                    </template>
                    <td v-else :colspan="g.cols.length" :class="[g.key, 'first', 'notfound']">Not found</td>
                  </template>
                  <td v-if="show('sync')"><span class="pill" :class="syncTone[r.sync]">{{ SYNC_LABELS[r.sync] }}</span></td>
                </tr>
                <tr v-if="expanded.has(r.awb)" class="detail">
                  <td :colspan="totalCols">
                    <div class="detail-grid">
                      <TrackingTimeline :record="r.smart_tracking" :title="labels.smart_tracking" tone="st" />
                      <TrackingTimeline :record="r.platform" :title="labels.platform" tone="pf" />
                    </div>
                  </td>
                </tr>
              </template>
              <tr v-if="!visibleRows.length"><td :colspan="totalCols" class="empty">No AWBs match these filters.
                <button class="linkbtn" @click="clearFilters">Clear filters</button></td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <section v-else-if="!loading" class="card card-pad empty">
      Paste AWB numbers above to see the current status in {{ labels.smart_tracking }} and {{ labels.platform }} side by side.
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import ColumnFilter from '../components/ColumnFilter.vue'
import ColumnPicker from '../components/ColumnPicker.vue'
import TrackingTimeline from '../components/TrackingTimeline.vue'
import { ageTone, fmtAge, fmtDate, fmtDateTime, hoursSince, SYNC_LABELS } from '../format'
import { downloadCsv, istDay, persisted } from '../persist'
import { appState } from '../store'

const route = useRoute()
const raw = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)
const expanded = ref(new Set())
const maxAwbs = ref(1000)
const labels = computed(() => appState.labels)
const showClosed = ref(false)
const closedNames = ref('Delivered, RTO Delivered, Pickup Cancelled, Lost, Damaged')
const closedCount = computed(() => (result.value?.rows || []).filter((r) => r.closed).length)
// Rows after skipping closed AWBs (codes 5, 13, 14, 15, 16) unless the user chose to show them.
const baseRows = computed(() => (result.value?.rows || []).filter((r) => showClosed.value || !r.closed))

const syncTone = { match: 'ok', mismatch: 'warn', only_smart_tracking: 'st', only_platform: 'pf', not_found: 'bad' }

// ---- columns -------------------------------------------------------------
const SRC_COLS = [
  { key: 'courier', label: 'Courier', type: 'values', get: (r) => r.courier },
  { key: 'status', label: 'Current Status', type: 'values', get: (r) => r.current_status },
  { key: 'status_datetime', label: 'Status Datetime', type: 'dates', get: (r) => r.status_datetime },
  { key: 'pickup_date', label: 'Pickup Date', type: 'dates', get: (r) => r.pickup_date },
  { key: 'last_track', label: 'Last Track', type: 'dates', get: (r) => r.last_track_datetime },
  { key: 'tracking', label: 'Tracking', type: 'values', get: (r) => r.tracking?.[0]?.status },
]
const GROUPS = [{ key: 'st', src: 'smart_tracking' }, { key: 'pf', src: 'platform' }]
const pickerColumns = computed(() => [
  { key: 'awb', label: 'AWB No.', locked: true },
  ...SRC_COLS.map((c, i) => ({ key: `st.${c.key}`, label: c.label, group: i === 0 ? labels.value.smart_tracking : null })),
  ...SRC_COLS.map((c, i) => ({ key: `pf.${c.key}`, label: c.label, group: i === 0 ? labels.value.platform : null })),
  { key: 'sync', label: 'Sync (match / mismatch)', group: 'Other' },
])
const defaultVisible = ['st', 'pf'].flatMap((g) => SRC_COLS.map((c) => `${g}.${c.key}`)).concat('sync')
const visible = persisted('awbcheck.columns.v1', defaultVisible)
const show = (k) => visible.value.includes(k)
const groupsShown = computed(() => GROUPS
  .map((g) => ({ ...g, label: labels.value[g.src], cols: SRC_COLS.filter((c) => show(`${g.key}.${c.key}`)) }))
  .filter((g) => g.cols.length))
const totalCols = computed(() => 1 + groupsShown.value.reduce((n, g) => n + g.cols.length, 0) + (show('sync') ? 1 : 0))
const rec = (r, g) => (g === 'st' ? r.smart_tracking : r.platform)

// ---- filters (all in the browser) ------------------------------------------
const filters = reactive({ awb: '', sync: [] })
GROUPS.forEach((g) => SRC_COLS.forEach((c) => { filters[`${g.key}.${c.key}`] = c.type === 'dates' ? { from: '', to: '' } : [] }))

function colOf(fkey) { const [, c] = fkey.split('.'); return SRC_COLS.find((x) => x.key === c) }
function valueOf(r, fkey) {
  if (fkey === 'sync') return r.sync
  const [g] = fkey.split('.')
  const rc = rec(r, g)
  if (!rc.found) return 'Not found'
  const v = colOf(fkey).get(rc)
  return v === null || v === undefined || v === '' ? '(blank)' : String(v)
}
function options(fkey) {
  const counts = new Map()
  for (const r of baseRows.value) {
    const v = valueOf(r, fkey)
    counts.set(v, (counts.get(v) || 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
    .map(([value, count]) => ({ value, count, label: fkey === 'sync' ? SYNC_LABELS[value] : value }))
}
function passes(r) {
  if (filters.awb.trim() && !r.awb.toLowerCase().includes(filters.awb.trim().toLowerCase())) return false
  for (const [fkey, f] of Object.entries(filters)) {
    if (fkey === 'awb') continue
    if (Array.isArray(f)) {
      if (f.length && !f.includes(valueOf(r, fkey))) return false
    } else if (f && (f.from || f.to)) {
      const rc = rec(r, fkey.split('.')[0])
      const day = rc.found ? istDay(colOf(fkey).get(rc)) : ''
      if (!day || (f.from && day < f.from) || (f.to && day > f.to)) return false
    }
  }
  return true
}
const visibleRows = computed(() => baseRows.value.filter(passes))
const activeFilterCount = computed(() => Object.entries(filters).filter(([k, f]) =>
  (k === 'awb' ? !!f.trim() : Array.isArray(f) ? f.length > 0 : !!(f.from || f.to))).length)
function clearFilters() {
  for (const [k, f] of Object.entries(filters)) {
    filters[k] = k === 'awb' ? '' : Array.isArray(f) ? [] : { from: '', to: '' }
  }
}

// ---- chips (quick filter on Sync) -------------------------------------------
const chips = computed(() => {
  const c = { total: baseRows.value.length }
  for (const r of baseRows.value) c[r.sync] = (c[r.sync] || 0) + 1
  return [
    { key: 'all', label: 'All', count: c.total, tone: '' },
    { key: 'match', label: 'Status match', count: c.match, tone: 'ok' },
    { key: 'mismatch', label: 'Mismatch', count: c.mismatch, tone: 'warn' },
    { key: 'only_smart_tracking', label: `Only ${labels.value.smart_tracking}`, count: c.only_smart_tracking, tone: 'st' },
    { key: 'only_platform', label: `Only ${labels.value.platform}`, count: c.only_platform, tone: 'pf' },
    { key: 'not_found', label: 'Not found', count: c.not_found, tone: 'bad' },
  ]
})
const activeChip = computed(() => (filters.sync.length === 0 ? 'all' : filters.sync.length === 1 ? filters.sync[0] : ''))
function setChip(k) { filters.sync = k === 'all' ? [] : [k] }

// ---- actions ----------------------------------------------------------------
const parsed = computed(() => {
  const seen = new Set()
  return raw.value.split(/[\s,;|]+/).map((s) => s.trim().replace(/^['"`]+|['"`]+$/g, '')).filter((s) => {
    const k = s.toUpperCase()
    if (!s || seen.has(k)) return false
    seen.add(k); return true
  })
})

function toggle(awb) {
  const s = new Set(expanded.value)
  s.has(awb) ? s.delete(awb) : s.add(awb)
  expanded.value = s
}
function expandAll() { expanded.value = new Set(visibleRows.value.map((r) => r.awb)) }

async function run() {
  if (!parsed.value.length) return
  loading.value = true; error.value = ''
  try {
    const res = await api.post('/api/awb/check', { awbs: parsed.value })
    result.value = res
    showClosed.value = false
    clearFilters()
    expanded.value = res.rows.length === 1 ? new Set([res.rows[0].awb]) : new Set()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const csvDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return iso
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(d).reduce((o, x) => ({ ...o, [x.type]: x.value }), {})
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`
}
function exportCsv() {
  const header = ['AWB']
  groupsShown.value.forEach((g) => g.cols.forEach((c) => header.push(`${g.label} - ${c.label}`)))
  if (show('sync')) header.push('Sync')
  const rows = visibleRows.value.map((r) => {
    const out = [r.awb]
    groupsShown.value.forEach((g) => {
      const rc = rec(r, g.key)
      g.cols.forEach((c) => {
        if (!rc.found) out.push('Not found')
        else if (c.key === 'tracking') out.push(rc.tracking?.length ? `${rc.tracking[0].status || ''} (${rc.tracking_count} events)` : '')
        else if (c.type === 'dates') out.push(csvDate(c.get(rc)))
        else out.push(c.get(rc) ?? '')
      })
    })
    if (show('sync')) out.push(SYNC_LABELS[r.sync])
    return out
  })
  const stamp = csvDate(new Date().toISOString()).replace(/[-: ]/g, '')
  downloadCsv(`awb_status_${stamp}.csv`, header, rows)
}

function clear() { raw.value = ''; result.value = null; error.value = '' }

onMounted(async () => {
  try {
    const cfg = await api.get('/api/config')
    maxAwbs.value = cfg.max_awbs
    if (cfg.closed_statuses?.length) closedNames.value = cfg.closed_statuses.join(', ')
  } catch { /* shown on run */ }
  if (route.query.awb) { raw.value = String(route.query.awb); run() }
})
</script>

<style scoped>
.input-card { margin-bottom: 16px; }
.input-row { display: flex; gap: 20px; align-items: flex-end; flex-wrap: wrap; }
.grow { flex: 1 1 420px; }
.awb-input { resize: vertical; min-height: 96px; font-size: .95rem; line-height: 1.5; }
.actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.count { color: var(--text-2); margin-right: 6px; }
.hint { font-size: .85rem; margin-top: 10px; }

.unmapped { display: block; font-size: .75rem; color: var(--warn); margin-top: 2px; cursor: help; }
.closed-note { background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--muted);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; color: var(--text-2); }
.closed-note.showing { border-left-color: var(--brand); }
.closed-pill { margin-left: 8px; font-size: .72rem; padding: 1px 8px; background: #eef0f3; color: var(--text-2); font-family: Inter, sans-serif; }
.results tbody tr.closed-row td { color: var(--text-2); background: #fafafa; }
.chips { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.chip {
  display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 999px;
  border: 1px solid var(--border-strong); background: var(--surface); cursor: pointer; font-weight: 500;
}
.chip:disabled { opacity: .45; cursor: default; }
.chip-num { font-weight: 700; }
.chip.ok .chip-num { color: var(--ok); } .chip.warn .chip-num { color: var(--warn); }
.chip.bad .chip-num { color: var(--bad); } .chip.st .chip-num { color: var(--st); } .chip.pf .chip-num { color: var(--pf); }
.chip.active { border-color: var(--text); box-shadow: inset 0 0 0 1px var(--text); }

.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 14px; flex-wrap: wrap; }
.tools { display: flex; gap: 10px; align-items: center; }
.linkbtn { background: none; border: 0; color: var(--brand); cursor: pointer; padding: 0; font-size: inherit; }

.results th.grp { text-align: center; font-size: .85rem; letter-spacing: .05em; border-bottom: 2px solid; }
.results th.grp.st { background: var(--st-soft); color: var(--st); border-bottom-color: var(--st); }
.results th.grp.pf { background: var(--pf-soft); color: var(--pf); border-bottom-color: var(--pf); }
.results thead tr:nth-child(2) th { top: 39px; }
.results th.sub.st { background: #f3f8fe; } .results th.sub.pf { background: #f8f4fe; }
.results .first { border-left: 1px solid var(--border-strong); }
.results tbody tr:not(.detail) { cursor: pointer; }
.results tbody tr.open td { background: #fbfcfe; }
.awb-col { font-weight: 500; }
.caret { display: inline-block; width: 16px; color: var(--muted); }
.status { font-weight: 600; }
.small { font-size: .8rem; margin-top: 2px; }
.notfound { color: var(--muted); font-style: italic; text-align: center; background: repeating-linear-gradient(-45deg, transparent 0 8px, #f6f7f9 8px 16px); }
.latest-ev { font-size: .9rem; }
.detail td { background: var(--surface-2) !important; padding: 16px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1000px) { .detail-grid { grid-template-columns: 1fr; } }
</style>
