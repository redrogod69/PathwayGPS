import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  // GitHub Pages serves the static demo under /<repo>/
  base: process.env.VITE_ENGINE === 'browser' ? (process.env.PAGES_BASE ?? '/PathwayGPS/') : '/',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, timeout: 300_000, proxyTimeout: 300_000 },
    },
  },
  preview: { host: '127.0.0.1', port: 4173, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } },
  build: {
    rollupOptions: { output: { manualChunks: { cytoscape: ['cytoscape'], react: ['react', 'react-dom'] } } },
  },
});
