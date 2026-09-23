import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app source lives in frontend/ (next to the Django backend in backend/).
// This root config lets managed hosting detect the Vite + React stack and run
// `vite build` from the repo root: the app is built from frontend/ and the
// static output lands in dist/ at the repo root. The managed preview keeps
// using scripts/dev.sh, which runs the Django API (:8000) and the frontend's
// own Vite dev server (with this same proxy) on $PORT.
//
// Production API base: the managed static host publishes dist/ as files only
// (no backend runtime behind /api), so production builds must point the SPA at
// the dedicated Django API host (Render — see render.yaml). A real
// VITE_API_BASE_URL in the build environment always wins; this constant is
// only the fallback so the deployed bundle is correct even when the build
// environment doesn't forward env vars. Dev builds are untouched — the dev
// proxy keeps serving /api same-origin. The client ignores values that are
// not ^https?:// URLs, so this is inert in any dev context.
const PROD_API_BASE_URL = 'https://smartspend-api.onrender.com/api';

export default defineConfig(({ mode }) => ({
  root: 'frontend',
  plugins: [react()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  ...(mode === 'production'
    ? {
        define: {
          'import.meta.env.VITE_API_BASE_URL': JSON.stringify(
            process.env.VITE_API_BASE_URL ?? PROD_API_BASE_URL,
          ),
        },
      }
    : {}),
  server: {
    // Same-origin dev proxy as frontend/vite.config.ts: /api and /media go to
    // the Django backend, so the app works no matter which host/port it is
    // exposed on. HMR config intentionally untouched.
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
}));
