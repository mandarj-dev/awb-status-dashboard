import { ref, watch } from 'vue'

// A ref remembered in this browser (e.g. which columns are visible). Safe if storage is blocked.
export function persisted(key, initial) {
  let start = initial
  try {
    const raw = localStorage.getItem(key)
    if (raw) start = JSON.parse(raw)
  } catch { /* storage unavailable */ }
  const r = ref(start)
  watch(r, (v) => { try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* ignore */ } }, { deep: true })
  return r
}

// CSV download built in the browser from rows already on screen.
export function downloadCsv(filename, header, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const text = '﻿' + [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n')
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' })), download: filename,
  })
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

// yyyy-mm-dd of an ISO datetime, in IST (used for date-range filters)
const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' })
export function istDay(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : dayFmt.format(d)
}
