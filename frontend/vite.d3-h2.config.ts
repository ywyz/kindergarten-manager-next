/** D3-A H2-only frontend build: independent output directory, never the
 * protected D1/D2 package or legacy frontend outputs. */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'chrome120',
    outDir: '../build/desktop-d3-h2/frontend',
    emptyOutDir: true,
    rollupOptions: {
      input: { index: fileURLToPath(new URL('./d1.html', import.meta.url)) },
    },
  },
})
