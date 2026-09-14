import axios from 'axios';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

const ACCESS_TOKEN = 'argus_token';
const REFRESH_TOKEN = 'argus_refresh_token';
let refreshPromise = null;

export function readSession() {
  return {
    accessToken: sessionStorage.getItem(ACCESS_TOKEN) || localStorage.getItem(ACCESS_TOKEN),
    refreshToken: sessionStorage.getItem(REFRESH_TOKEN) || localStorage.getItem(REFRESH_TOKEN),
  };
}

export function saveSession(payload) {
  sessionStorage.setItem(ACCESS_TOKEN, payload.access_token);
  sessionStorage.setItem(REFRESH_TOKEN, payload.refresh_token);
  localStorage.setItem(ACCESS_TOKEN, payload.access_token);
  localStorage.setItem(REFRESH_TOKEN, payload.refresh_token);
}

export function clearSession() {
  sessionStorage.removeItem(ACCESS_TOKEN);
  sessionStorage.removeItem(REFRESH_TOKEN);
  localStorage.removeItem(ACCESS_TOKEN);
  localStorage.removeItem(REFRESH_TOKEN);
}

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = readSession().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const { accessToken, refreshToken } = readSession();
    const isAuthRequest = original?.url?.includes('/auth/login') || original?.url?.includes('/auth/refresh');
    if (error.response?.status === 401 && accessToken && refreshToken && !original?._retried && !isAuthRequest) {
      original._retried = true;
      refreshPromise ||= axios.post(`${API_BASE}/api/v1/auth/refresh`, { refresh_token: refreshToken })
        .then(response => { saveSession(response.data); return response.data.access_token; })
        .finally(() => { refreshPromise = null; });
      try {
        const token = await refreshPromise;
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      } catch { /* handled below */ }
    }
    if (error.response?.status === 401 && accessToken) {
      clearSession();
      window.dispatchEvent(new CustomEvent('argus:unauthorized'));
    }
    return Promise.reject(error);
  }
);

export default api;
