const TZ = 'Asia/Kolkata'
const dtFmt = new Intl.DateTimeFormat('en-IN', {
  timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
})
const dFmt = new Intl.DateTimeFormat('en-IN', { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric' })

export function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? iso : dtFmt.format(d)
}

export function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? iso : dFmt.format(d)
}

export function hoursSince(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return isNaN(d) ? null : (Date.now() - d.getTime()) / 36e5
}

export function fmtAge(hours) {
  if (hours === null || hours === undefined) return '—'
  if (hours < 0) return 'just now'
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m ago`
  if (hours < 24) return `${Math.floor(hours)}h ago`
  const d = Math.floor(hours / 24)
  const h = Math.floor(hours % 24)
  return h ? `${d}d ${h}h ago` : `${d}d ago`
}

// green < 24h, amber < 72h, red beyond
export function ageTone(hours) {
  if (hours === null || hours === undefined) return 'muted'
  if (hours < 24) return 'ok'
  if (hours < 72) return 'warn'
  return 'bad'
}

export const SYNC_LABELS = {
  match: 'Status match',
  mismatch: 'Status mismatch',
  only_smart_tracking: 'Only in Smart Tracking',
  only_platform: 'Only in Platform',
  not_found: 'Not found',
}

export function fmtNum(n) {
  return (n ?? 0).toLocaleString('en-IN')
}
