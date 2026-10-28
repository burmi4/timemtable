const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  let data = null
  try { data = await res.json() } catch { /* empty body */ }
  if (!res.ok) {
    const detail = data && data.detail
    throw new Error(typeof detail === 'string' ? detail : `Ошибка ${res.status}`)
  }
  return data
}

export const api = {
  me: () => request('/me'),
  register: (firstName, lastName) =>
    request('/auth/register', { method: 'POST', body: JSON.stringify({ first_name: firstName, last_name: lastName }) }),
  login: (firstName, lastName) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ first_name: firstName, last_name: lastName }) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  timetable: () => request('/timetable'),
  status: () => request('/status'),
  sync: () => request('/sync', { method: 'POST' }),
  signup: (lessonId) => request(`/lessons/${lessonId}/signup`, { method: 'POST' }),
  cancelSignup: (lessonId) => request(`/lessons/${lessonId}/signup`, { method: 'DELETE' }),
}
