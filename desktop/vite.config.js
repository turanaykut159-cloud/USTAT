import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Build anında sabitlenen tarih — Settings.jsx "Hakkında" kartında kullanılır.
// YYYY-MM-DD formatı (UTC). Her `npm run build` çalıştığında otomatik güncellenir.
const BUILD_DATE_ISO = new Date().toISOString().slice(0, 10);

export default defineConfig({
  plugins: [react()],
  base: './',
  root: '.',
  publicDir: 'public',
  define: {
    // Vite `define` — derleme zamanında string literal olarak inline edilir.
    __BUILD_DATE__: JSON.stringify(BUILD_DATE_ISO),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@components': path.resolve(__dirname, 'src/components'),
      '@services': path.resolve(__dirname, 'src/services'),
      '@styles': path.resolve(__dirname, 'src/styles'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
});
