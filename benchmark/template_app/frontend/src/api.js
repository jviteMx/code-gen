// Thin fetch wrapper over the Kanbanlite API.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.status === 204 ? null : res.json()
}

export function getBoards() {
  return request('/api/boards')
}

export function getBoard(id) {
  return request(`/api/boards/${id}`)
}

export function createCard(columnId, data) {
  return request(`/api/columns/${columnId}/cards`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function moveCard(cardId, columnId, position) {
  const params = new URLSearchParams({ column_id: columnId })
  if (position != null) params.set('position', position)
  return request(`/api/cards/${cardId}/move?${params}`, { method: 'POST' })
}

export function deleteCard(cardId) {
  return request(`/api/cards/${cardId}`, { method: 'DELETE' })
}
