import axios from 'axios'

/** Axios instance for FastAPI routes (Vite proxies `/api` → backend). */
export const api = axios.create({ baseURL: '/api', withCredentials: true })
let sessionGeneration = 0

export function advanceSession() {
  sessionGeneration += 1
}

export function createAuthenticatedClient() {
  const generation = sessionGeneration
  const scoped = axios.create({ baseURL: '/api', withCredentials: true })
  let controller = new AbortController()
  scoped.interceptors.request.use(config => {
    if (generation !== sessionGeneration || controller.signal.aborted) {
      throw new axios.CanceledError('The user session changed')
    }
    config.signal = controller.signal
    config.sessionGeneration = generation
    return config
  })
  scoped.interceptors.response.use(response => response, handleError)
  return {
    api: scoped,
    activate() { if (controller.signal.aborted) controller = new AbortController() },
    dispose() { controller.abort() },
  }
}

api.interceptors.request.use(config => {
  config.sessionGeneration = sessionGeneration
  return config
})

// Broadcast session loss so App can return to the login screen.
function handleError(err) {
  const url = err.config?.url || ''
  if (err.response?.status === 401 && err.config?.sessionGeneration === sessionGeneration &&
      !url.includes('/auth/login') && !url.includes('/auth/me')) {
    window.dispatchEvent(new CustomEvent('gj:unauthorized'))
  }
  return Promise.reject(err)
}

api.interceptors.response.use(response => response, handleError)
