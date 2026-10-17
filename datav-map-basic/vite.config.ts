import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 8081,
    proxy: {
      '/geoserver': {
        target: 'http://8.146.208.20',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
  build: {
    sourcemap: true,
    target: 'es2020',
  },
})
