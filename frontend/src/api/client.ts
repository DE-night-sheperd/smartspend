import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';

// Same-origin by default: in dev, /api goes through the Vite dev proxy to
// Django; a deployed static build expects the API at same-origin /api too.
// A build-time VITE_API_BASE_URL points a deployed frontend at an API hosted
// elsewhere — honoured in `vite build` output (import.meta.env.PROD) and in
// split local dev on localhost. Hosted dev previews always use the
// same-origin proxy so a stale local .env can never break them.
//
// PROD bridge: the managed static host only ships dist/, so the deployed app
// has no same-origin /api — it talks to the Django API exposed by the
// workspace tunnel instead. That URL is committed here (not passed as a
// build env var) because the hosting builder routes env values through a
// runtime envelope Vite cannot read at build time. Update it if the
// workspace API host changes, or point it at a dedicated API host later.
const PROD_API_BRIDGE =
  'https://8000-2826ecac-f239-4972-b4d9-c0041cf83a05.daytonaproxy01.net/api';

const isLocalhost =
  typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
const envApiUrl = import.meta.env.VITE_API_BASE_URL;
// Only trust the env var when it is a real URL — the managed platform can
// wrap env values in an opaque runtime envelope, which must never become
// the axios baseURL.
const envApiUrlOk =
  typeof envApiUrl === 'string' && /^https?:\/\//.test(envApiUrl);
export const API_BASE_URL = import.meta.env.PROD
  ? envApiUrlOk
    ? envApiUrl
    : PROD_API_BRIDGE
  : isLocalhost
    ? envApiUrlOk
      ? envApiUrl
      : '/api'
    : '/api';

const ACCESS_KEY = 'smartspend_access';
const REFRESH_KEY = 'smartspend_refresh';

export const tokenStore = {
  getAccess: () => localStorage.getItem(ACCESS_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  setTokens: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

export const api = axios.create({ baseURL: API_BASE_URL });

// The deployed app reaches the API through a tunnel that can return 502/503
// with "proxy upstream error" while the API server behind it wakes up (the
// first request itself starts the wake). Those are transient — retry
// transparently for up to ~30s so a cold start is absorbed silently and the
// user only ever sees the button's normal "Sending…" state.
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [1500, 3000, 5000, 8000, 12000];

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const access = tokenStore.getAccess();
  if (access) {
    config.headers.Authorization = `Bearer ${access}`;
  }
  return config;
});

// On a 401, try to refresh the access token once and replay the request.
// This mirrors the JWT flow from djangorestframework-simplejwt on the backend.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) return null;
  try {
    const { data } = await axios.post(`${API_BASE_URL}/auth/refresh/`, { refresh });
    tokenStore.setTokens(data.access, refresh);
    return data.access as string;
  } catch {
    tokenStore.clear();
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
      _gatewayRetry?: boolean;
    };
    const status = error.response?.status;
    // Retry transient gateway errors (server waking behind the proxy).
    if (
      status &&
      RETRYABLE_STATUS.has(status) &&
      original &&
      !original._gatewayRetry
    ) {
      original._gatewayRetry = true;
      for (const wait of RETRY_DELAYS_MS) {
        await delay(wait);
        try {
          return await api(original);
        } catch (retryError) {
          const retryStatus = (retryError as AxiosError).response?.status;
          if (!retryStatus || !RETRYABLE_STATUS.has(retryStatus)) {
            throw retryError;
          }
          error = retryError as AxiosError;
        }
      }
    }
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      refreshPromise = refreshPromise || refreshAccessToken();
      const newAccess = await refreshPromise;
      refreshPromise = null;
      if (newAccess) {
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${newAccess}`;
        return api(original);
      }
    }
    return Promise.reject(error);
  },
);
