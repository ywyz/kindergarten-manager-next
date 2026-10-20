/** D0-only frontend build: same Vue/Element Plus stack, separate entry and a
 * root output dir under build/desktop-d0/frontend so the D0 packaging and the
 * normal app build (if any) never share outputs. The output filename is
 * normalized to index.html to keep the local server shell trivial.
 */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'chrome120',
    outDir: '../build/desktop-d0/frontend',
    emptyOutDir: true,
    rollupOptions: {
      input: { index: fileURLToPath(new URL('./d0.html', import.meta.url)) },
    },
  },
})
