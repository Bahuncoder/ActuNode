/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api (including the /api/ws WebSocket) is proxied to the FastAPI backend.
// In Docker, nginx does the same proxying (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
  },
  server: {
    // Only the shared contract fixtures outside this folder may be read (used by tests, D-38).
    fs: { allow: ['.', '../contracts'] },
    proxy: {
      '/api': {
        target: process.env.ACTUNODE_API_URL ?? 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
