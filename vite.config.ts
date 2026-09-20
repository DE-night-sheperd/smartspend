import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app source lives in frontend/ (next to the Django backend in backend/).
// This root config lets managed hosting detect the Vite + React stack and run
// `vite build` from the repo root: the app is built from frontend/ and the
// static output lands in dist/ at the repo root. The managed preview keeps
// using scripts/dev.sh, which runs the Django API (:8000) and the frontend's
// own Vite dev server (with this same proxy) on $PORT.
export default defineConfig({
  root: 'frontend',
  plugins: [react()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    // Same-origin dev proxy as frontend/vite.config.ts: /api and /media go to
    // the Django backend, so the app works no matter which host/port it is
    // exposed on. HMR config intentionally untouched.
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
})
