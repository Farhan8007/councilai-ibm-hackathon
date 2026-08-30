const API_BASE = 'http://127.0.0.1:8000'

/**
 * POST /review
 * @param {string} diff
 * @param {string|null} context
 * @returns {Promise<import('./types').ReviewResponse>}
 */
export async function postReview(diff, context = null) {
  const res = await fetch(`${API_BASE}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ diff, context }),
  })

  if (!res.ok) {
    const text = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(`HTTP ${res.status}: ${text}`)
  }

  return res.json()
}
