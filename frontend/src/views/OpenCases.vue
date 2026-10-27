<template>
  <div class="page">
    <section class="card card-pad filters">
      <div class="seg" role="tablist">
        <button v-for="(lbl, k) in labels" :key="k" class="seg-btn" :class="{ active: source === k }"
          @click="setSource(k)">{{ lbl }}</button>
      </div>
      <div class="field"><label>Order date from</label><input v-model="created.from" type="date" class="input" @change="schedule()" /></div>
      <div class="field"><label>Order date to</label><input v-model="created.to" type="date" class="input" @change="schedule()" /></div>
      <div class="field wide"><label>Courier</label>
        <ColumnFilter v-model="cf.courier" dropdown all-text="All couriers" title="Courier" :options="colOptions('courier')" /></div>
      <div class="field wide"><label>Current status</label>
        <ColumnFilter v-model="cf.status" dropdown all-text="All open statuses" title="Current status" :options="colOptions('status')" /></div>
      <div class="filter-actions">
        <button class="btn" :disabled="loading" @click="reload"><span v-if="loading" class="spinner"></span>Refresh</button>
        <button v-if="activeTags.length || created.from || created.to" class="btn btn-ghost" @click="clearAll">Clear all filters</button>
      </div>
    </section>
    <div class="scope muted">
      Open = current status not in closed list ({{ closed.join(', ') }}).
      <span v-if="!created.from && !created.to && lookback">Order date in the last {{ lookback }} days.</span>
      Pick couriers and statuses above, or use the <span class="funnel">⏷</span> in any column header below.
      <span v-if="summary"> Updated {{ fmtDateTime(summary.generated_at) }}.</span>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <section v-if="summary" class="kpis">
      <button class="kpi total" :class="{ active: !cf.age.length }" @click="cf.age = []">
        <span class="kpi-label">Open cases</span>
        <span class="kpi-val num">{{ fmtNum(summary.total) }}</span>
        <span class="kpi-sub">{{ summary.source_label }}</span>
      </button>
      <button v-for="a in summary.aging" :key="a.key" class="kpi" :class="[agingTone[a.key], { active: cf.age.includes(a.key) }]"
        :disabled="!a.count" @click="toggleIn('age', a.key)">
        <span class="kpi-label">Since last update</span>
        <span class="kpi-val num">{{ fmtNum(a.count) }}</span>
        <span class="kpi-sub">{{ a.label }}</span>
      </button>
    </section>

    <section v-if="summary" class="breakdowns">
      <div v-for="b in breakdowns" :key="b.key" class="card card-pad">
        <h3 class="card-title">{{ b.title }} <span class="card-sub">{{ b.rows.length }} · click to filter</span></h3>
        <div class="bars">
          <button v-for="r in b.rows.slice(0, expandedBd[b.key] ? 200 : 10)" :key="r.label" class="bar-row"
            :class="{ active: cf[b.key].includes(r.label) }" @click="toggleIn(b.key, r.label)">
            <span class="bar-label" :title="r.label">{{ r.label }}</span>
            <span class="bar-track"><span class="bar-fill" :style="{ width: pct(r.count, b.max) }"></span></span>
            <span class="bar-val num">{{ fmtNum(r.count) }}</span>
          </button>
          <div v-if="!b.rows.length" class="muted">No data</div>
        </div>
        <button v-if="b.rows.length > 10" class="btn btn-ghost btn-sm" @click="expandedBd[b.key] = !expandedBd[b.key]">
          {{ expandedBd[b.key] ? 'Show top 10' : `Show all ${b.rows.length}` }}</button>
      </div>
    </section>

    <section v-if="list" class="card">
      <div class="list-head">
        <h3 class="card-title">Cases <span class="card-sub num">{{ fmtNum(list.total) }} matching</span>
          <span v-for="t in activeTags" :key="t.key" class="pill tag">{{ t.label }}
            <button class="x" title="Remove this filter" @click="clearCol(t.key)">×</button></span>
        </h3>
        <div class="list-tools">
          <select v-model="sort" class="input" @change="loadList(1)">
            <option value="stale">Oldest update first</option>
            <option value="recent">Newest shipments first</option>
          </select>
          <ColumnPicker v-model="visible" :columns="pickerColumns" :defaults="defaultVisible" />
          <button class="btn" :disabled="exporting || !list.total" @click="exportCsv">
            <span v-if="exporting" class="spinner"></span>Export CSV</button>
        </div>
      </div>
      <div v-if="list.capped" class="warnbox">Showing the first {{ fmtNum(list.total) }} matches for the
        {{ otherLabel }} filter — narrow the other filters to see everything.</div>
      <div class="table-wrap">
        <table class="grid">
          <thead><tr>
            <th v-for="c in shownCols" :key="c.key" :class="{ nowrap: true }">
              {{ c.label }}
              <ColumnFilter v-if="c.filter" v-model="cf[c.key]" :type="c.filter" :title="c.label"
                :options="colOptions(c.key)" :placeholder="c.key === 'awb' ? 'AWB starts with…' : ''" />
            </th>
            <th></th>
          </tr></thead>
          <tbody>
            <tr v-for="r in list.rows" :key="r.awb">
              <td v-for="c in shownCols" :key="c.key" :class="c.cls">
                <template v-if="c.key === 'status'"><strong>{{ r.current_status || '—' }}</strong></template>
                <template v-else-if="c.key === 'age'"><span class="pill" :class="ageTone(r.age_hours)">{{ fmtAge(r.age_hours).replace(' ago', '') }}</span></template>
                <template v-else-if="c.key === 'other_status'">
                  <template v-if="r.other.found">
                    <span :class="{ 'tone-warn': r.other.sync === 'mismatch' }">{{ r.other.current_status || '—' }}</span>
                    <span v-if="r.other.sync === 'mismatch'" class="pill warn mini" title="Status differs between systems">≠</span>
                  </template>
                  <span v-else class="muted">Not found</span>
                </template>
                <template v-else>{{ c.show(r) }}</template>
              </td>
              <td><RouterLink :to="{ path: '/awb-check', query: { awb: r.awb } }" class="btn btn-sm">Track</RouterLink></td>
            </tr>
            <tr v-if="!list.rows.length"><td :colspan="shownCols.length + 1" class="empty">No open cases for these filters.
              <button class="linkbtn" @click="clearAll">Clear all filters</button></td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span class="muted">Page {{ list.page }} of {{ pages }}</span>
        <select v-model.number="pageSize" class="input sm" @change="loadList(1)">
          <option :value="25">25 / page</option><option :value="50">50 / page</option>
          <option :value="100">100 / page</option><option :value="200">200 / page</option>
        </select>
        <button class="btn btn-sm" :disabled="list.page <= 1 || listLoading" @click="loadList(list.page - 1)">‹ Prev</button>
        <button class="btn btn-sm" :disabled="list.page >= pages || listLoading" @click="loadList(list.page + 1)">Next ›</button>
        <span v-if="listLoading" class="spinner muted"></span>
      </div>
    </section>

    <section v-if="loading && !summary" class="card card-pad empty"><span class="spinner"></span> Loading open cases…</section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import ColumnFilter from '../components/ColumnFilter.vue'
import ColumnPicker from '../components/ColumnPicker.vue'
import { ageTone, fmtAge, fmtDate, fmtDateTime, fmtNum } from '../format'
import { persisted } from '../persist'
import { appState } from '../store'

const labels = computed(() => appState.labels)
const closed = ref([])
const lookback = ref(0)
const source = ref('smart_tracking')
const created = reactive({ from: '', to: '' })
const filterOpts = ref({ couriers: [], statuses: [] })
const summary = ref(null)
const list = ref(null)
const sort = ref('stale')
const pageSize = ref(50)
const loading = ref(false)
const listLoading = ref(false)
const exporting = ref(false)
const error = ref('')
const expandedBd = reactive({ status: false, courier: false })

const otherLabel = computed(() => labels.value[source.value === 'smart_tracking' ? 'platform' : 'smart_tracking'])
const srcLabel = computed(() => labels.value[source.value])
const agingTone = { lt1d: 'ok', '1to2d': 'ok', '2to3d': 'warn', '3to5d': 'bad', gt5d: 'bad', nodate: 'muted' }
const SYNC_OPTS = { match: 'Same status', mismatch: 'Different status', not_found: 'Not found' }

// ---- columns ----------------------------------------------------------------
const COLS = computed(() => [
  { key: 'awb', label: 'AWB No.', filter: 'text', locked: true, cls: 'mono nowrap', show: (r) => r.awb },
  { key: 'courier', label: 'Courier', filter: 'values', show: (r) => r.courier || '—' },
  { key: 'status', label: `${srcLabel.value} Status`, filter: 'values' },
  { key: 'order_date', label: 'Order Date', cls: 'nowrap', show: (r) => fmtDate(r.order_date) },
  { key: 'status_datetime', label: 'Status Datetime', filter: 'dates', cls: 'nowrap', show: (r) => fmtDateTime(r.status_datetime) },
  { key: 'pickup_date', label: 'Pickup Date', filter: 'dates', cls: 'nowrap', show: (r) => fmtDate(r.pickup_date) },
  { key: 'last_track', label: 'Last Track', filter: 'dates', cls: 'nowrap', show: (r) => fmtDateTime(r.last_track_datetime) },
  { key: 'age', label: 'Since Update', filter: 'values', cls: 'nowrap' },
  { key: 'other_status', label: `${otherLabel.value} Status`, filter: 'values' },
  { key: 'other_status_datetime', label: `${otherLabel.value} Status Datetime`, cls: 'nowrap', show: (r) => fmtDateTime(r.other.status_datetime) },
  { key: 'other_last_track', label: `${otherLabel.value} Last Track`, cls: 'nowrap', show: (r) => fmtDateTime(r.other.last_track_datetime) },
])
const defaultVisible = ['awb', 'courier', 'status', 'order_date', 'status_datetime', 'pickup_date', 'last_track', 'age', 'other_status']
const visible = persisted('opencases.columns.v2', defaultVisible)
const pickerColumns = computed(() => COLS.value.map(({ key, label, locked }) => ({ key, label, locked })))
const shownCols = computed(() => COLS.value.filter((c) => c.locked || visible.value.includes(c.key)))

// ---- column filters (sent to the server) -------------------------------------
const blankFilters = () => ({
  awb: '', courier: [], status: [], status_datetime: { from: '', to: '' }, pickup_date: { from: '', to: '' },
  last_track: { from: '', to: '' }, age: [], other_status: [],
})
const cf = reactive(blankFilters())

function colOptions(key) {
  const s = summary.value
  const withCounts = (names, rows) => {
    const counts = new Map((rows || []).map((x) => [x.label.toLowerCase(), x.count]))
    const all = new Set([...names, ...(rows || []).map((x) => x.label)])
    return [...all].map((v) => ({ value: v, count: counts.get(v.toLowerCase()) ?? 0 })).sort((a, b) => b.count - a.count)
  }
  if (key === 'courier') return withCounts(filterOpts.value.couriers, s?.by_courier)
  if (key === 'status') return withCounts(filterOpts.value.statuses, s?.by_status)
  if (key === 'age') return (s?.aging || []).map((a) => ({ value: a.key, label: a.label, count: a.count }))
  if (key === 'other_status') return Object.entries(SYNC_OPTS).map(([value, label]) => ({ value, label: `${label}` }))
  return []
}

function params(extra = {}) {
  const d = (r) => r || undefined
  return {
    source: source.value, date_from: d(created.from), date_to: d(created.to),
    awb: cf.awb.trim() || undefined, courier: cf.courier, status: cf.status,
    status_from: d(cf.status_datetime.from), status_to: d(cf.status_datetime.to),
    pickup_from: d(cf.pickup_date.from), pickup_to: d(cf.pickup_date.to),
    track_from: d(cf.last_track.from), track_to: d(cf.last_track.to),
    aging: cf.age, other: cf.other_status, ...extra,
  }
}

const activeTags = computed(() => {
  const t = []
  const dr = (r) => `${r.from ? fmtDate(r.from) : '…'} – ${r.to ? fmtDate(r.to) : '…'}`
  const many = (arr, map) => (arr.length > 2 ? `${arr.length} selected` : arr.map((v) => map?.(v) ?? v).join(', '))
  if (cf.awb.trim()) t.push({ key: 'awb', label: `AWB: ${cf.awb.trim()}…` })
  if (cf.courier.length) t.push({ key: 'courier', label: `Courier: ${many(cf.courier)}` })
  if (cf.status.length) t.push({ key: 'status', label: `Status: ${many(cf.status)}` })
  if (cf.status_datetime.from || cf.status_datetime.to) t.push({ key: 'status_datetime', label: `Status date: ${dr(cf.status_datetime)}` })
  if (cf.pickup_date.from || cf.pickup_date.to) t.push({ key: 'pickup_date', label: `Pickup: ${dr(cf.pickup_date)}` })
  if (cf.last_track.from || cf.last_track.to) t.push({ key: 'last_track', label: `Last track: ${dr(cf.last_track)}` })
  if (cf.age.length) t.push({ key: 'age', label: `Since update: ${many(cf.age, (k) => summary.value?.aging.find((a) => a.key === k)?.label)}` })
  if (cf.other_status.length) t.push({ key: 'other_status', label: `${otherLabel.value}: ${many(cf.other_status, (k) => SYNC_OPTS[k])}` })
  return t
})

function clearCol(key) { cf[key] = blankFilters()[key] }
function clearAll() { Object.assign(cf, blankFilters()); created.from = ''; created.to = ''; schedule() }
function toggleIn(key, val) { cf[key] = cf[key].includes(val) ? cf[key].filter((x) => x !== val) : [...cf[key], val] }

// ---- breakdowns ---------------------------------------------------------------
const breakdowns = computed(() => {
  if (!summary.value) return []
  const mk = (key, title, rows) => ({ key, title, rows, max: Math.max(1, ...rows.map((r) => r.count)) })
  return [mk('status', 'By current status', summary.value.by_status), mk('courier', 'By courier', summary.value.by_courier)]
})
const pct = (n, max) => `${Math.max(2, (n / max) * 100)}%`
const pages = computed(() => Math.max(1, Math.ceil((list.value?.total || 0) / pageSize.value)))

// ---- loading ------------------------------------------------------------------
async function loadSummary() { summary.value = await api.get('/api/open-cases/summary', params()) }

async function loadList(page = 1) {
  listLoading.value = true
  try {
    list.value = await api.get('/api/open-cases/list', params({ sort: sort.value, page, page_size: pageSize.value }))
  } catch (e) { error.value = e.message } finally { listLoading.value = false }
}

async function loadOptions() {
  try { filterOpts.value = await api.get('/api/open-cases/filters', { source: source.value }) } catch { /* non-fatal */ }
}

let seq = 0
async function reload() {
  const my = ++seq
  loading.value = true; error.value = ''
  try {
    await Promise.all([loadSummary(), loadList(1)])
  } catch (e) { if (my === seq) error.value = e.message } finally { if (my === seq) loading.value = false }
}

// Any filter change reloads summary + list (aging/other only affect the list).
// Changes made together (e.g. "Clear all") are merged into one reload.
let pending = null
function schedule(listOnly = false) {
  if (pending && !listOnly) pending.full = true
  if (pending) return
  pending = { full: !listOnly }
  setTimeout(() => {
    const full = pending.full
    pending = null
    full ? reload() : loadList(1)
  }, 30)
}
watch(() => JSON.stringify({ ...cf, age: null, other_status: null }), () => schedule())
watch(() => JSON.stringify([cf.age, cf.other_status]), () => schedule(true))

function setSource(k) {
  if (source.value === k) return
  source.value = k
  Object.assign(cf, blankFilters())
  loadOptions(); schedule()
}

const EXPORT_KEYS = {
  awb: ['awb'], courier: ['courier'], status: ['status'], order_date: ['order_date'], status_datetime: ['status_datetime'],
  pickup_date: ['pickup_date'], last_track: ['last_track'], age: ['age'],
  other_status: ['other_status', 'other_sync'], other_status_datetime: ['other_status_datetime'],
  other_last_track: ['other_last_track'],
}
async function exportCsv() {
  exporting.value = true; error.value = ''
  try {
    const columns = shownCols.value.flatMap((c) => EXPORT_KEYS[c.key] || [])
    await api.download('/api/open-cases/export', { params: params({ sort: sort.value, columns }) })
  } catch (e) { error.value = e.message } finally { exporting.value = false }
}

onMounted(async () => {
  try {
    const cfg = await api.get('/api/config')
    closed.value = cfg.closed_statuses
    lookback.value = cfg.open_lookback_days
  } catch { /* handled by reload */ }
  loadOptions()
  reload()
})
</script>

<style scoped>
.filters { display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; }
.filters .field { flex: 0 1 170px; }
.filters .field.wide { flex: 0 1 230px; }
.filter-actions { display: flex; gap: 8px; }
.seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--border-strong); border-radius: 9px; padding: 3px; align-self: flex-end; }
.seg-btn { border: 0; background: transparent; padding: 7px 14px; border-radius: 7px; cursor: pointer; font-weight: 500; color: var(--text-2); }
.seg-btn.active { background: var(--surface); color: var(--brand); box-shadow: var(--shadow); }
.scope { font-size: .85rem; margin: 10px 2px 16px; }
.funnel { color: var(--brand); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
.kpi {
  display: flex; flex-direction: column; gap: 4px; text-align: left; padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); cursor: pointer;
  border-top: 3px solid var(--border-strong);
}
.kpi:disabled { cursor: default; opacity: .6; }
.kpi.active { outline: 2px solid var(--text); outline-offset: -1px; }
.kpi.total { border-top-color: var(--brand); }
.kpi.ok { border-top-color: var(--ok); } .kpi.warn { border-top-color: var(--warn); } .kpi.bad { border-top-color: var(--bad); }
.kpi-label { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
.kpi-val { font-size: 1.8rem; font-weight: 700; line-height: 1.1; }
.kpi.ok .kpi-val { color: var(--ok); } .kpi.warn .kpi-val { color: var(--warn); } .kpi.bad .kpi-val { color: var(--bad); }
.kpi-sub { font-size: .9rem; color: var(--text-2); }

.breakdowns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 1000px) { .breakdowns { grid-template-columns: 1fr; } }
.bars { display: flex; flex-direction: column; gap: 2px; margin-bottom: 6px; }
.bar-row {
  display: grid; grid-template-columns: minmax(120px, 34%) 1fr 70px; gap: 12px; align-items: center; padding: 6px 8px;
  border: 0; background: transparent; border-radius: 6px; cursor: pointer; text-align: left;
}
.bar-row:hover { background: var(--surface-2); }
.bar-row.active { background: var(--brand-soft); }
.bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { height: 10px; background: var(--surface-2); border-radius: 5px; overflow: hidden; }
.bar-fill { display: block; height: 100%; background: var(--brand); border-radius: 5px; opacity: .8; }
.bar-val { text-align: right; font-weight: 600; }

.list-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px 8px; flex-wrap: wrap; }
.list-head .card-title { margin: 0; flex-wrap: wrap; }
.list-tools { display: flex; gap: 10px; align-items: center; }
.tag { gap: 6px; background: var(--brand-soft); color: var(--brand); border-color: transparent; }
.x { border: 0; background: none; color: inherit; cursor: pointer; font-size: 1rem; line-height: 1; padding: 0; }
.mini { padding: 0 7px; margin-left: 6px; }
.pill.muted { color: var(--muted); }
.warnbox { margin: 0 18px 10px; background: var(--warn-soft); color: var(--warn); padding: 10px 12px; border-radius: 8px; }
.linkbtn { background: none; border: 0; color: var(--brand); cursor: pointer; padding: 0; font-size: inherit; }
.pager { display: flex; align-items: center; gap: 10px; padding: 12px 18px; justify-content: flex-end; }
.input.sm { padding: 5px 8px; font-size: .85rem; }
</style>
