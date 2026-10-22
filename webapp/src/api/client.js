import axios from 'axios'

/** Axios instance for FastAPI routes (Vite proxies `/api` → backend). */
export const api = axios.create({ baseURL: '/api', withCredentials: true })

// Broadcast session loss so App can return to the login screen.
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || ''
    if (err.response?.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/me')) {
      window.dispatchEvent(new CustomEvent('gj:unauthorized'))
    }
    return Promise.reject(err)
  }
)
