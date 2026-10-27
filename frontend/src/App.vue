<template>
  <header class="topbar">
    <div class="brand">
      <span class="logo">⬢</span>
      <span class="name">AWB Status Dashboard</span>
      <span class="tag">B2B</span>
    </div>
    <nav class="tabs">
      <RouterLink to="/awb-check" class="tab">AWB Check</RouterLink>
      <RouterLink to="/open-cases" class="tab">Open Cases</RouterLink>
      <RouterLink to="/setup" class="tab">⚙ Settings</RouterLink>
    </nav>
    <div class="health" :title="healthTitle">
      <span v-for="(s, k) in health" :key="k" class="dot-wrap">
        <span class="dot" :class="s.ok ? 'up' : 'down'"></span>{{ labels[k] || k }}
      </span>
    </div>
  </header>
  <div v-if="appState.backendDown" class="down">
    The dashboard program isn't responding. Make sure its window is still open (or restart it), then refresh this page.
  </div>
  <RouterView />
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from './api'
import { appState } from './store'

const health = ref({})
const labels = ref({ smart_tracking: 'Smart Tracking', platform: 'Platform' })

const healthTitle = computed(() => Object.entries(health.value)
  .map(([k, v]) => `${labels.value[k] || k}: ${v.ok ? 'connected' : v.error}`).join('\n'))

async function loadHealth() {
  if (!appState.configured) { health.value = {}; return }
  try {
    labels.value = { ...appState.labels }
    health.value = (await api.get('/api/health')).sources
  } catch { /* backend unreachable: pages will show the error */ }
}
onMounted(loadHealth)
watch(() => appState.configured, loadHealth)
</script>

<style scoped>
.topbar {
  display: flex; align-items: center; gap: 28px; padding: 0 28px; height: 60px; background: var(--surface);
  border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 20;
}
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.05rem; }
.logo { color: var(--brand); font-size: 1.3rem; }
.tag { font-size: .7rem; font-weight: 600; padding: 2px 7px; border-radius: 5px; background: var(--brand-soft); color: var(--brand); }
.tabs { display: flex; gap: 4px; height: 100%; }
.tab {
  display: flex; align-items: center; padding: 0 14px; color: var(--text-2); font-weight: 500;
  border-bottom: 2px solid transparent; text-decoration: none !important;
}
.tab:hover { color: var(--text); }
.tab.router-link-active { color: var(--brand); border-bottom-color: var(--brand); }
.health { margin-left: auto; display: flex; gap: 16px; font-size: .85rem; color: var(--text-2); }
.dot-wrap { display: inline-flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.dot.up { background: var(--ok); } .dot.down { background: var(--bad); }
.down { margin: 20px 28px 0; background: var(--bad-soft); color: var(--bad); padding: 14px 18px; border-radius: 10px; font-weight: 500; }
@media (max-width: 760px) {
  .topbar { padding: 0 16px; gap: 14px; } .health, .tag { display: none; }
}
</style>
