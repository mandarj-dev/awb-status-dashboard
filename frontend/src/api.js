const BASE = import.meta.env.VITE_API_BASE || ''

async function handle(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* not json */ }
    throw new Error(msg)
  }
  return res
}

function qs(params) {
  const p = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach((x) => { if (x !== null && x !== undefined && x !== '') p.append(k, x) })
    else if (v !== null && v !== undefined && v !== '') p.set(k, v)
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  async get(path, params) {
    return (await handle(await fetch(`${BASE}${path}${qs(params)}`))).json()
  },
  async post(path, body, headers = {}) {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body),
    })
    return (await handle(res)).json()
  },
  async download(path, { body, params, filename }) {
    const res = await handle(await fetch(`${BASE}${path}${qs(params)}`, body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : {}))
    const cd = res.headers.get('Content-Disposition') || ''
    const m = cd.match(/filename="?([^"]+)"?/)
    const blob = await res.blob()
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob), download: (m && m[1]) || filename || 'export.csv',
    })
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(a.href), 2000)
  },
}
