const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function getJson(path) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    let detail = `Request failed for ${path}: ${response.status}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = payload.detail
      }
    } catch {
      //
    }
    throw new Error(detail)
  }
  return response.json()
}

async function postJson(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = `Request failed for ${path}: ${response.status}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = payload.detail
      }
    } catch {
      //
    }
    throw new Error(detail)
  }
  return response.json()
}

function toQueryString(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    query.set(key, String(value))
  })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

export async function getHealth() {
  try {
    return await getJson('/health')
  } catch (error) {
    return { status: 'offline', detail: error.message }
  }
}

export async function getMockTournamentSnapshot(params = {}) {
  return getJson(`/api/mock/snapshot${toQueryString(params)}`)
}

export async function generateDemoTournament(params = {}) {
  return postJson(`/api/demo/tournament${toQueryString(params)}`, {})
}

export async function getValidationSnapshot(params = {}) {
  return getJson(`/api/validate/snapshot${toQueryString(params)}`)
}

export async function getRescheduleDemo(params = {}) {
  return getJson(`/api/reschedule/demo${toQueryString(params)}`)
}

export async function postRescheduleDemo(body) {
  return postJson('/api/reschedule/apply', body)
}

export async function postLiveOperations(body) {
  return postJson('/api/operations/live', body)
}

export async function getDivisionDetail(divisionId, params = {}) {
  return getJson(`/api/divisions/${divisionId}/detail${toQueryString(params)}`)
}

export async function postDivisionDetail(divisionId, body) {
  return postJson(`/api/divisions/${divisionId}/detail`, body)
}

export async function getRepairDemo(params = {}) {
  return getJson(`/api/repair/demo${toQueryString(params)}`)
}

export async function postRepairDemo(body) {
  return postJson('/api/repair/apply', body)
}

export async function importCsvTournament(file, params = {}) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE}/api/import/csv${toQueryString(params)}`, {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    let detail = `CSV import failed: ${response.status}`
    try {
      const payload = await response.json()
      if (payload?.detail) detail = payload.detail
    } catch {
      //
    }
    throw new Error(detail)
  }
  return response.json()
}
