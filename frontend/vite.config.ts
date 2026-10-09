import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api is proxied to the FastAPI backend.
// In Docker, nginx does the same proxying (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.ACTUNODE_API_URL ?? 'http://localhost:8000',
    },
  },
})
