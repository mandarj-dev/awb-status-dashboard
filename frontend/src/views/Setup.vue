<template>
  <div class="page setup">
    <div class="intro">
      <h1>{{ status?.configured ? 'Settings' : 'Welcome — let’s connect your databases' }}</h1>
      <p class="muted">Fill in the two boxes below, click <b>Test connection</b>, choose the database and collection,
        and check the sample shipment. Then click <b>Save</b>. You only do this once.</p>
    </div>

    <!-- <div v-if="status?.readonly_env" class="warnbox vercel-note">
      This app is running on Vercel (read-only filesystem). The Setup page can <b>test</b> connections, but
      settings must be saved as <b>Environment Variables</b> in the Vercel project
      (<code>ST_MONGO_URI</code>, <code>ST_DB_NAME</code>, <code>ST_COLLECTION</code>, and the matching
      <code>PF_*</code> keys), then redeploy. See the README “Deploy on Vercel” section.
    </div> -->

    <div v-if="loadError" class="error">{{ loadError }}</div>

    <section v-if="status && !(status.pin_required && !pinOk)" class="card card-pad sample-box">
      <div class="field">
        <label for="sample-awb">Sample AWB used to check the setup</label>
        <div class="sample-row">
          <input id="sample-awb" v-model.trim="sampleDraft" class="input mono" placeholder="e.g. 1095160"
            @keydown.enter="sampleAwb = sampleDraft" @blur="sampleAwb = sampleDraft" />
          <button class="btn" :disabled="sampleDraft === sampleAwb" @click="sampleAwb = sampleDraft">Use this AWB</button>
        </div>
        <span class="muted small-note">Both databases below show this shipment, so you can check each column against a
          shipment you know.</span>
      </div>
    </section>

    <!-- PIN gate when settings are protected -->
    <section v-if="status?.pin_required && !pinOk" class="card card-pad pin-gate">
      <h2>Settings are protected</h2>
      <p class="muted">Enter the settings PIN to change the database connection.</p>
      <div class="row">
        <input v-model="pin" type="password" class="input" placeholder="PIN" @keydown.enter="verifyPin" />
        <button class="btn btn-primary" @click="verifyPin">Unlock</button>
        <RouterLink to="/awb-check" class="btn btn-ghost">Back to dashboard</RouterLink>
      </div>
      <div v-if="pinMsg" class="tone-bad msg">{{ pinMsg }}</div>
    </section>

    <template v-else-if="status">
      <SourceSetup :step="1" :title="status.smart_tracking.label + ' database'" tone="st" side-key="smart_tracking"
        :sample-awb="sampleAwb"
        subtitle="Where Smart Tracking stores its shipments." :saved="status.smart_tracking" :pin="pin"
        @change="st = $event" />

      <SourceSetup :step="2" :title="status.platform.label + ' (Instalogix) database'" tone="pf" side-key="platform"
        :sample-awb="sampleAwb"
        subtitle="Where Instalogix stores its shipments." :saved="status.platform" :pin="pin"
        allow-same-server :same-server-label="status.smart_tracking.label"
        :initial-same-server="status.platform_same_server"
        :shared-uri="st ? { ...st.conn, ok: st.ok } : null" @change="pf = $event" />

      <section class="card card-pad">
        <div class="pin-head"><span class="step-no">3</span>
          <div><h2>Protect settings <span class="muted opt">(optional)</span></h2>
            <p class="muted">Recommended on a shared server: a PIN stops others from changing the database connection.
              <span v-if="status.pin_required">A PIN is already set — leave empty to keep it.</span></p></div></div>
        <div class="row"><input v-model="newPin" type="password" class="input pin-in" placeholder="New PIN (4+ characters)" autocomplete="new-password" /></div>
      </section>

      <section v-if="mapping.length || mappingError" class="card card-pad map-card">
        <div class="pin-head"><span class="step-no">i</span>
          <div><h2>Status names</h2>
            <p class="muted">Read from <b>Dispatch-status-Mapping.xlsx</b> in the dashboard folder. To change a name, edit
              that file in Excel and restart the dashboard. <b>Closed</b> statuses are skipped on both pages.</p></div></div>
        <div v-if="mappingError" class="warnbox">⚠ {{ mappingError }}</div>
        <div class="status-grid">
          <div v-for="m in mapping" :key="m.code" class="status-item" :class="{ closed: m.closed }">
            <span class="code mono">{{ m.code }}</span><span>{{ m.label }}</span>
            <span v-if="m.closed" class="pill closed-tag">Closed · skipped</span>
          </div>
        </div>
      </section>

      <div class="save-bar">
        <span v-if="!canSave" class="muted">{{ missing }}</span>
        <span v-if="saveMsg" class="tone-bad msg">{{ saveMsg }}</span>
        <button class="btn btn-primary btn-lg" :disabled="!canSave || saving" @click="save">
          <span v-if="saving" class="spinner"></span>{{ saving ? 'Saving…' : 'Save and open dashboard' }}</button>
      </div>
    </template>

    <section v-else-if="!loadError" class="card card-pad empty"><span class="spinner"></span> Loading…</section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import SourceSetup from '../components/SourceSetup.vue'
import { refreshAppState } from '../store'

const router = useRouter()
const status = ref(null)
const loadError = ref('')
const st = ref(null)
const pf = ref(null)
const pin = ref('')
const sampleAwb = ref('')
const mapping = ref([])
const mappingError = ref('')
const sampleDraft = ref('')
const pinOk = ref(false)
const pinMsg = ref('')
const newPin = ref('')
const saving = ref(false)
const saveMsg = ref('')

const canSave = computed(() =>
  !status.value?.readonly_env
  && st.value?.ready && pf.value?.ready
  && (!newPin.value || newPin.value.length >= 4))
const missing = computed(() => {
  if (status.value?.readonly_env) {
    return 'On Vercel, set ST_* / PF_* env vars in the project settings instead of Save.'
  }
  if (!st.value?.ok) return 'Step 1: test the Smart Tracking connection.'
  if (!st.value?.ready) return 'Step 1: choose the database and collection.'
  if (!pf.value?.ok) return 'Step 2: connect the Instalogix database.'
  if (!pf.value?.ready) return 'Step 2: choose the database and collection.'
  if (newPin.value && newPin.value.length < 4) return 'The PIN needs at least 4 characters.'
  return ''
})

async function verifyPin() {
  pinMsg.value = ''
  try {
    await api.post('/api/setup/verify-pin', {}, { 'X-Setup-Pin': pin.value })
    pinOk.value = true
  } catch (e) { pinMsg.value = e.message }
}

function side(s) {
  return { ...(s.sameServer ? {} : s.conn), db: s.db, collection: s.collection, fields: s.fields }
}

async function save() {
  saving.value = true; saveMsg.value = ''
  try {
    await api.post('/api/setup/save', {
      smart_tracking: side(st.value), platform: side(pf.value),
      platform_same_server: !!pf.value.sameServer, new_pin: newPin.value || null, sample_awb: sampleAwb.value,
    }, pin.value ? { 'X-Setup-Pin': pin.value } : {})
    await refreshAppState()
    router.push('/awb-check')
  } catch (e) { saveMsg.value = e.message } finally { saving.value = false }
}

onMounted(async () => {
  try {
    status.value = await api.get('/api/setup/status')
    api.get('/api/config').then((c) => { mapping.value = c.status_mapping || []; mappingError.value = c.status_mapping_error || '' })
      .catch(() => {})
    sampleAwb.value = sampleDraft.value = status.value.sample_awb || ''
  } catch (e) {
    loadError.value = `Can't reach the dashboard program: ${e.message}. Is the black window still open?`
  }
})
</script>

<style scoped>
.setup { max-width: 1100px; margin: 0 auto; }
.intro h1 { margin: 6px 0 6px; font-size: 1.6rem; }
.intro p { margin: 0 0 20px; font-size: 1.02rem; }
.sample-box { margin-bottom: 18px; }
.map-card { margin-top: 18px; }
.status-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; margin-top: 14px; }
.status-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; flex-wrap: wrap; }
.status-item .code { min-width: 26px; height: 26px; border-radius: 6px; background: var(--brand-soft); color: var(--brand); display: grid; place-items: center; font-weight: 600; font-size: .85rem; }
.status-item.closed { background: var(--surface-2); color: var(--text-2); }
.status-item.closed .code { background: #e7e9ee; color: var(--text-2); }
.closed-tag { font-size: .72rem; padding: 1px 8px; margin-left: auto; }
.warnbox { margin-top: 10px; background: var(--warn-soft); color: var(--warn); padding: 10px 12px; border-radius: 8px; }
.vercel-note { margin: 0 0 18px; line-height: 1.45; }
.vercel-note code { font-size: .9em; }
.sample-row { display: flex; gap: 10px; margin-top: 2px; }
.sample-row .input { max-width: 260px; font-size: 1rem; }
.small-note { font-size: .85rem; margin-top: 6px; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
.pin-gate h2, .pin-head h2 { margin: 0; font-size: 1.25rem; }
.pin-head { display: flex; gap: 14px; align-items: flex-start; }
.pin-head p { margin: 4px 0 0; }
.step-no { flex: none; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; color: #fff; background: var(--text-2); }
.opt { font-weight: 400; font-size: .95rem; }
.pin-in { max-width: 280px; }
.msg { font-weight: 500; }
.save-bar { position: sticky; bottom: 0; display: flex; justify-content: flex-end; align-items: center; gap: 16px; padding: 16px 0; margin-top: 8px; background: linear-gradient(to top, var(--bg) 70%, transparent); flex-wrap: wrap; }
.btn-lg { padding: 12px 22px; font-size: 1.05rem; }
</style>
