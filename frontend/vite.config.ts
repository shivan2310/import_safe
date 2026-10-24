import { defineConfig } from 'vite';

export default defineConfig({
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, timeout: 135000, proxyTimeout: 135000 } } },
});
