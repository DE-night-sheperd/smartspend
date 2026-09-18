import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin dev proxy: the frontend calls /api and /media and Vite
    // forwards them to the Django backend, so the app works no matter which
    // host/port the dev server is exposed on. HMR config intentionally untouched.
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
})
