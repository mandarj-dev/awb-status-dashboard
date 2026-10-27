<template>
  <section class="card card-pad src" :class="tone">
    <div class="src-head">
      <span class="step-no">{{ step }}</span>
      <div>
        <h2>{{ title }}</h2>
        <p class="muted">{{ subtitle }}</p>
      </div>
      <span v-if="ready" class="pill ok done">✓ Ready</span>
    </div>

    <!-- 1. Connection -->
    <div v-if="allowSameServer" class="same">
      <label class="check"><input v-model="sameServer" type="checkbox" @change="onSameChange" />
        Same database server as {{ sameServerLabel }}</label>
    </div>

    <div v-if="needsOwnConnection" class="block">
      <div class="block-title">Connection</div>

      <div v-if="savedAvailable && useSaved" class="saved">
        <span>Using the saved connection <span class="mono muted">{{ savedMasked }}</span></span>
        <button class="btn btn-sm" @click="useSaved = false; connected = false">Change</button>
      </div>

      <template v-else>
        <div class="seg small-seg">
          <button :class="{ active: mode === 'simple' }" @click="mode = 'simple'">Enter details</button>
          <button :class="{ active: mode === 'uri' }" @click="mode = 'uri'">Paste connection link</button>
        </div>

        <div v-if="mode === 'simple'" class="form-grid">
          <div class="field span2"><label>Server address</label>
            <input v-model.trim="f.host" class="input" placeholder="e.g. 10.0.1.25  or  db.mycompany.com" /></div>
          <div class="field"><label>Port</label>
            <input v-model.trim="f.port" class="input" placeholder="27017" /></div>
          <div class="field"><label>Username</label>
            <input v-model.trim="f.user" class="input" autocomplete="off" placeholder="leave empty if none" /></div>
          <div class="field"><label>Password</label>
            <div class="pw"><input v-model="f.password" :type="showPw ? 'text' : 'password'" class="input" autocomplete="new-password" />
              <button class="btn btn-ghost btn-sm" type="button" @click="showPw = !showPw">{{ showPw ? 'Hide' : 'Show' }}</button></div></div>
          <div class="field"><label>Login database</label>
            <input v-model.trim="f.authdb" class="input" placeholder="admin" /></div>
          <label class="check span3"><input v-model="f.direct" type="checkbox" /> Connect directly to this server
            <span class="muted">(keep ticked unless told otherwise)</span></label>
        </div>
        <div v-else class="field">
          <label>Connection link</label>
          <input v-model.trim="f.uri" class="input mono" placeholder="mongodb://user:password@host:27017/?authSource=admin" />
          <div class="hint">Tip: you can copy the <b>MONGO_URI</b> line from your Smart Tracking Dashboard's <b>.env</b>
            file and paste it here as it is.</div>
        </div>
      </template>

      <div class="row">
        <button class="btn btn-primary" :disabled="busy.test || !canTest" @click="testConnection">
          <span v-if="busy.test" class="spinner"></span>{{ busy.test ? 'Connecting…' : 'Test connection' }}</button>
        <span v-if="testMsg" :class="connected ? 'tone-ok' : 'tone-bad'" class="msg">
          {{ connected ? '✓' : '✕' }} {{ testMsg }}</span>
      </div>
      <details v-if="testDetail && !connected" class="tech"><summary>Technical detail (for IT)</summary>
        <code>{{ testDetail }}</code></details>
    </div>

    <!-- 2. Database + collection -->
    <div v-if="connectionOk" class="block">
      <div class="block-title">Where are the shipments stored?</div>
      <div class="form-grid">
        <div class="field span2"><label>Database</label>
          <select v-if="databases.length" v-model="dbName" class="input" @change="loadCollections">
            <option value="" disabled>Choose a database</option>
            <option v-for="d in databases" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-else v-model.trim="dbName" class="input" placeholder="type the database name" @change="loadCollections" />
        </div>
        <div class="field span2"><label>Collection (table)</label>
          <select v-model="collection" class="input" :disabled="!collections.length" @change="inspect()">
            <option value="" disabled>{{ busy.cols ? 'Loading…' : 'Choose a collection' }}</option>
            <option v-for="c in collections" :key="c.name" :value="c.name">
              {{ c.name }}{{ c.count !== null ? ` — ${c.count.toLocaleString('en-IN')} records` : '' }}</option>
          </select>
        </div>
      </div>
      <div v-if="colMsg" class="tone-bad msg">{{ colMsg }}</div>
    </div>

    <!-- 3. Preview -->
    <div v-if="busy.inspect" class="block muted"><span class="spinner"></span> Reading a sample shipment…</div>
    <div v-else-if="insp" class="block">
      <div class="block-title">Sample shipment
        <span v-if="insp.sample_awb" class="pill ok">AWB {{ insp.sample_awb }}</span>
        <span v-else-if="insp.ok" class="pill">newest shipment</span>
        — does this look right?</div>
      <div v-if="!insp.ok" class="tone-bad msg">{{ insp.message }}</div>
      <template v-else>
        <div v-for="w in insp.warnings" :key="w" class="warnbox">⚠ {{ w }}</div>
        <div v-if="insp.status_suggestions?.length" class="suggest">
          <div class="suggest-title">Fields that hold a dispatch status from your mapping file:</div>
          <div v-for="sg in insp.status_suggestions" :key="sg.path" class="suggest-row">
            <span v-if="sg.event">Latest tracking event's code</span>
            <span v-else class="mono">{{ sg.path }}</span>
            <span>= <strong>{{ sg.sample }}</strong> ({{ sg.label }})</span>
            <button class="btn btn-sm btn-primary" @click="picked.status = sg.path; inspect(true)">Use this field</button>
          </div>
        </div>
        <p class="muted map-help">Each dashboard column is read from a field in the database. We picked them
          automatically; change any dropdown if the sample value on the right doesn't look right.</p>
        <div class="map-wrap">
          <table class="map">
            <thead><tr><th>Dashboard column</th><th>Field in database</th><th>Value in sample shipment</th></tr></thead>
            <tbody>
              <template v-for="row in COLUMNS" :key="row.key">
                <tr v-if="row.group" class="grp-row"><td colspan="3">{{ row.group }}</td></tr>
                <tr :class="{ missing: row.required && !picked[row.key] }">
                  <td class="col-name">{{ row.label }}<span v-if="row.required" class="req">required</span></td>
                  <td>
                    <select v-model="picked[row.key]" class="input" @change="inspect(true)">
                      <option :value="row.blankValue || ''">{{ row.blank }}</option>
                      <option v-for="x in optionsFor(row)" :key="x.path" :value="x.path">{{ x.path }}  ·  {{ x.sample }}</option>
                    </select>
                  </td>
                  <td class="sample" :class="{ none: !sampleFor(row.key) }">{{ sampleFor(row.key) || '—' }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { fmtDate, fmtDateTime } from '../format'

const props = defineProps({
  step: Number, title: String, subtitle: String, tone: String, sideKey: String,
  saved: Object,                   // saved settings from /api/setup/status
  pin: String,
  allowSameServer: Boolean, sameServerLabel: String,
  sharedUri: Object,               // { uri, use_saved } from the first card when "same server"
  initialSameServer: { type: Boolean, default: true },
  sampleAwb: { type: String, default: '' },
})
const emit = defineEmits(['change'])

const mode = ref('simple')
const showPw = ref(false)
const f = reactive({ host: '', port: '27017', user: '', password: '', authdb: 'admin', direct: true, uri: '' })
const savedAvailable = computed(() => !!props.saved?.has_uri)
const savedMasked = computed(() => props.saved?.uri_masked)
const useSaved = ref(savedAvailable.value)
const sameServer = ref(props.allowSameServer ? props.initialSameServer : false)
const needsOwnConnection = computed(() => !(props.allowSameServer && sameServer.value))

const connected = ref(false)
const testMsg = ref('')
const testDetail = ref('')
const databases = ref([])
const dbName = ref(props.saved?.db || '')
const collections = ref([])
const collection = ref(props.saved?.collection || '')
const colMsg = ref('')
const insp = ref(null)
const busy = reactive({ test: false, cols: false, inspect: false })
const COLUMNS = [
  { key: 'awb', label: 'AWB number', where: 'doc', required: true, blank: '— choose —', group: 'Shipment' },
  { key: 'courier', label: 'Courier', where: 'doc', blank: '— not available —' },
  { key: 'status', label: 'Current status', where: 'doc', blank: '— use latest tracking event code —', blankValue: '@latest_tracking_event' },
  { key: 'status_date', label: 'Status datetime', where: 'doc', blank: '— use latest tracking event —' },
  { key: 'pickup_date', label: 'Pickup date', where: 'doc', blank: '— not available —' },
  { key: 'order_date', label: 'Order date (Open Cases date range)', where: 'doc', blank: '— not available —' },
  { key: 'last_track', label: 'Last track datetime', where: 'doc', blank: '— use latest tracking event —' },
  { key: 'tracking', label: 'Tracking list', where: 'array', blank: '— no tracking list —', group: 'Courier tracking block' },
  { key: 'track_status', label: 'Event status', where: 'event', blank: '— not available —' },
  { key: 'track_date', label: 'Event date/time', where: 'event', blank: '— not available —' },
  { key: 'track_location', label: 'Event location', where: 'event', blank: '— not available —' },
]
const picked = reactive(Object.fromEntries(COLUMNS.map((c) => [c.key, ''])))

function optionsFor(row) {
  const i = insp.value || {}
  return (row.where === 'array' ? i.arrays : row.where === 'event' ? i.event_fields : i.fields) || []
}

function sampleFor(key) {
  const pv = insp.value?.preview || {}
  const ev = (pv.tracking || [])[0] || {}
  switch (key) {
    case 'awb': return pv.awb
    case 'courier': return pv.courier
    case 'status': return pv.current_status
    case 'status_date': return pv.status_datetime && fmtDateTime(pv.status_datetime)
    case 'pickup_date': return pv.pickup_date && fmtDate(pv.pickup_date)
    case 'order_date': return pv.order_date && fmtDateTime(pv.order_date)
    case 'last_track': return pv.last_track_datetime && fmtDateTime(pv.last_track_datetime)
    case 'tracking': return pv.tracking_count ? `${pv.tracking_count} event${pv.tracking_count === 1 ? '' : 's'}` : ''
    case 'track_status': return ev.status
    case 'track_date': return ev.datetime && fmtDateTime(ev.datetime)
    case 'track_location': return ev.location
    default: return ''
  }
}

function buildUri() {
  if (mode.value === 'uri') return f.uri
  let host = f.host.replace(/^mongodb(\+srv)?:\/\//, '').replace(/\/.*$/, '')
  if (!host) return ''
  const srv = /mongodb\.net$/i.test(host)
  const auth = f.user ? `${encodeURIComponent(f.user)}:${encodeURIComponent(f.password)}@` : ''
  const p = new URLSearchParams()
  if (f.user && f.authdb) p.set('authSource', f.authdb)
  if (f.direct && !srv) p.set('directConnection', 'true')
  if (!srv && f.port && !host.includes(':')) host = `${host}:${f.port}`
  const qs = p.toString()
  return `mongodb${srv ? '+srv' : ''}://${auth}${host}/${qs ? '?' + qs : ''}`
}

// what to send to the API for this card's connection
const conn = computed(() => {
  if (!needsOwnConnection.value) return props.sharedUri || {}
  if (savedAvailable.value && useSaved.value) return { use_saved: props.sideKey }
  return { uri: buildUri() }
})
const canTest = computed(() => !!(conn.value.uri || conn.value.use_saved))
const connectionOk = computed(() => (needsOwnConnection.value ? connected.value : !!props.sharedUri?.ok))
const ready = computed(() => !!(insp.value?.ok && picked.awb && dbName.value && collection.value))

const headers = () => (props.pin ? { 'X-Setup-Pin': props.pin } : {})

async function call(path, body) {
  return api.post(path, { ...conn.value, ...body }, headers())
}

async function testConnection() {
  busy.test = true; testMsg.value = ''; testDetail.value = ''
  try {
    const r = await call('/api/setup/test', {})
    connected.value = r.ok; testMsg.value = r.message; testDetail.value = r.detail || ''
    if (r.ok) {
      databases.value = r.databases || []
      if (dbName.value && (databases.value.includes(dbName.value) || !databases.value.length)) loadCollections()
      else if (databases.value.length === 1) { dbName.value = databases.value[0]; loadCollections() }
    }
  } catch (e) { connected.value = false; testMsg.value = e.message } finally { busy.test = false; emitChange() }
}

async function loadCollections() {
  if (!dbName.value) return
  busy.cols = true; colMsg.value = ''; collections.value = []; insp.value = null
  try {
    const r = await call('/api/setup/collections', { db: dbName.value })
    if (!r.ok) { colMsg.value = r.message; return }
    collections.value = r.collections
    if (!r.collections.length) colMsg.value = 'This database has no collections. Please choose another database.'
    if (collection.value && r.collections.some((c) => c.name === collection.value)) inspect()
    else collection.value = ''
  } catch (e) { colMsg.value = e.message } finally { busy.cols = false; emitChange() }
}

async function inspect(useManual = false) {
  if (!collection.value) return
  busy.inspect = true
  const sameAsSaved = props.saved?.collection === collection.value && props.saved?.db === dbName.value
  const manual = useManual ? { ...picked } : (sameAsSaved ? { ...(props.saved?.fields || {}) } : {})
  try {
    const r = await call('/api/setup/inspect', { db: dbName.value, collection: collection.value, side: props.sideKey, fields: manual, sample_awb: props.sampleAwb })
    insp.value = r
    if (r.ok) Object.assign(picked, r.chosen)
  } catch (e) { insp.value = { ok: false, message: e.message } } finally { busy.inspect = false; emitChange() }
}

function onSameChange() { connected.value = false; databases.value = []; collections.value = []; insp.value = null; emitChange() }

function emitChange() {
  emit('change', {
    conn: conn.value, ok: connectionOk.value, ready: ready.value, sameServer: needsOwnConnection.value === false,
    db: dbName.value, collection: collection.value, fields: { ...picked },
  })
}

// When this card shares the first card's server, follow its connection.
watch(() => props.sharedUri?.ok, async (ok) => {
  if (!needsOwnConnection.value) {
    if (ok) {
      try {
        const r = await call('/api/setup/test', {})
        databases.value = r.ok ? r.databases || [] : []
        if (dbName.value) loadCollections()
      } catch { /* shown on first card */ }
    } else { databases.value = []; collections.value = []; insp.value = null }
    emitChange()
  }
}, { immediate: true })

// A different sample AWB: re-read, keeping any fields already chosen.
watch(() => props.sampleAwb, () => { if (collection.value && insp.value) inspect(true) })

// Editing later with a saved connection: connect straight away.
if (savedAvailable.value && needsOwnConnection.value) testConnection()

watch([dbName, collection, () => mode.value, () => ({ ...f }), useSaved], () => emitChange(), { deep: true })
</script>

<style scoped>
.src { margin-bottom: 18px; }
.src.st { border-top: 4px solid var(--st); } .src.pf { border-top: 4px solid var(--pf); }
.src-head { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 8px; }
.src-head h2 { margin: 0; font-size: 1.25rem; }
.src-head p { margin: 4px 0 0; }
.step-no { flex: none; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; color: #fff; background: var(--brand); }
.src.st .step-no { background: var(--st); } .src.pf .step-no { background: var(--pf); }
.done { margin-left: auto; font-size: .95rem; padding: 5px 12px; }
.block { border-top: 1px solid var(--border); padding-top: 16px; margin-top: 16px; }
.block-title { font-weight: 600; margin-bottom: 12px; }
.form-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.span2 { grid-column: span 2; } .span3 { grid-column: span 3; }
@media (max-width: 760px) { .form-grid { grid-template-columns: 1fr; } .span2, .span3 { grid-column: auto; } }
.pw { display: flex; gap: 6px; } .pw .input { flex: 1; }
.check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.check input { width: 18px; height: 18px; }
.same { margin: 12px 0 0; font-weight: 500; }
.row { display: flex; align-items: center; gap: 14px; margin-top: 14px; flex-wrap: wrap; }
.msg { font-weight: 500; }
.tech { margin-top: 8px; font-size: .85rem; color: var(--muted); }
.tech code { display: block; white-space: pre-wrap; margin-top: 6px; background: var(--surface-2); padding: 8px; border-radius: 6px; }
.saved { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.small-seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--border-strong); border-radius: 9px; padding: 3px; margin-bottom: 14px; }
.small-seg button { border: 0; background: transparent; padding: 6px 14px; border-radius: 7px; cursor: pointer; color: var(--text-2); font-weight: 500; }
.small-seg button.active { background: var(--surface); color: var(--brand); box-shadow: var(--shadow); }
.map-help { margin: 4px 0 12px; }
.suggest { border: 1px solid var(--brand); background: var(--brand-soft); border-radius: 10px; padding: 12px 14px; margin: 10px 0 12px; }
.suggest-title { font-weight: 600; margin-bottom: 8px; }
.suggest-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 4px 0; }
.map-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }
.map { width: 100%; border-collapse: collapse; font-size: .95rem; }
.map th { text-align: left; font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--text-2); background: var(--surface-2); padding: 9px 12px; }
.map td { padding: 8px 12px; border-top: 1px solid var(--border); vertical-align: middle; }
.map .grp-row td { background: var(--surface-2); font-weight: 600; font-size: .85rem; color: var(--text-2); padding: 7px 12px; }
.map .col-name { font-weight: 500; white-space: nowrap; width: 22%; }
.map td:nth-child(2) { width: 42%; } .map select { width: 100%; }
.map .sample { font-weight: 600; } .map .sample.none { color: var(--muted); font-weight: 400; }
.map tr.missing td { background: var(--bad-soft); }
.req { margin-left: 8px; font-size: .7rem; color: var(--bad); text-transform: uppercase; font-weight: 600; }
.preview { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.preview div { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
.preview span { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
.warnbox { margin-top: 10px; background: var(--warn-soft); color: var(--warn); padding: 10px 12px; border-radius: 8px; }
.fix { margin-top: 14px; }
.hint { font-size: .88rem; color: var(--text-2); margin-top: 6px; }
.fix summary { cursor: pointer; color: var(--brand); font-weight: 500; margin-bottom: 12px; }
</style>
