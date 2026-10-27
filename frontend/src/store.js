import { reactive } from 'vue'
import { api } from './api'

// App-wide state: is the app set up yet, and the labels of the two systems.
export const appState = reactive({
  loaded: false,
  configured: false,
  labels: { smart_tracking: 'Smart Tracking', platform: 'Platform' },
  backendDown: false,
})

export async function refreshAppState() {
  try {
    const cfg = await api.get('/api/config')
    appState.configured = cfg.configured
    appState.labels = { smart_tracking: cfg.sources.smart_tracking.label, platform: cfg.sources.platform.label }
    appState.backendDown = false
  } catch {
    appState.backendDown = true
  }
  appState.loaded = true
  return appState
}
