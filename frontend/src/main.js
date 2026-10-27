import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import AwbCheck from './views/AwbCheck.vue'
import OpenCases from './views/OpenCases.vue'
import Setup from './views/Setup.vue'
import { appState, refreshAppState } from './store'
import './styles.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/awb-check' },
    { path: '/awb-check', component: AwbCheck, meta: { title: 'AWB Check' } },
    { path: '/open-cases', component: OpenCases, meta: { title: 'Open Cases' } },
    { path: '/setup', component: Setup, meta: { title: 'Setup' } },
    { path: '/:pathMatch(.*)*', redirect: '/awb-check' },
  ],
})
// Until the databases are connected, every page goes to Setup.
router.beforeEach(async (to) => {
  if (!appState.loaded) await refreshAppState()
  if (!appState.configured && !appState.backendDown && to.path !== '/setup') return '/setup'
})
router.afterEach((to) => { document.title = `${to.meta.title || ''} · AWB Status Dashboard` })

createApp(App).use(router).mount('#app')
