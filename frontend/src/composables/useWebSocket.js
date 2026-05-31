import { ref } from 'vue'

const API_BASE = '/api'

export function useWebSocket() {
  const ws = ref(null)
  const connected = ref(false)

  function connect(runId, onMessage) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/api/evaluations/ws/${runId}`
    ws.value = new WebSocket(url)
    ws.value.onopen = () => { connected.value = true }
    ws.value.onmessage = (e) => { onMessage(JSON.parse(e.data)) }
    ws.value.onclose = () => { connected.value = false }
    ws.value.onerror = () => { connected.value = false }
  }

  function disconnect() {
    if (ws.value) ws.value.close()
  }

  return { connect, disconnect, connected }
}

export async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API Error: ${res.status}`)
  return res.json()
}
