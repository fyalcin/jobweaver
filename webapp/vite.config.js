import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
const projectDir = fileURLToPath(new URL('.', import.meta.url))
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  worker: {
    format: 'es'
  },
  assetsInclude: ['**/*.wasm'],
  optimizeDeps: {
    exclude: ['@myriaddreamin/typst-ts-web-compiler', '@myriaddreamin/typst-ts-renderer']
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(projectDir, 'index.html'),
        testWorker: resolve(projectDir, 'test-typst-worker.html')
      }
    }
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false
      }
    }
  }
})
