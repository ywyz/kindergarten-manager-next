/** D1-only frontend build: same Vue/Element Plus stack, separate entry and a
 * root output dir under build/desktop-d1/frontend so the D1 package never
 * shares outputs with the D0 probe or the legacy app build. The output name
 * is normalized to index.html for the local server shell.
 */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'chrome120',
    outDir: '../build/desktop-d1/frontend',
    emptyOutDir: true,
    rollupOptions: {
      input: { index: fileURLToPath(new URL('./d1.html', import.meta.url)) },
    },
  },
})
