import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://construction-backend:5001',  
        changeOrigin: true,
        timeout: 60000, 
      },
      '/analytics': {
        target: 'http://construction-backend:5001', 
        changeOrigin: true,
      }
    }
  }
})